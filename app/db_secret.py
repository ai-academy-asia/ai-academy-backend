"""Resolve the database password from Secrets Manager as each connection opens.

RDS rotates the ``aiaa_admin`` master password every 7 days, but the password
lives inline in ``DATABASE_URL``. Written once into ``.env`` it goes stale at the
first rotation, and from then on every new connection is refused with
``password authentication failed`` — the API answers 500 while RDS itself is
perfectly healthy. That is not hypothetical: it is how the service went down.

So the password carried by the URL is treated as a fallback, not as the truth.
When ``DB_SECRET_ARN`` is set, the live one is read from Secrets Manager (via the
EC2 instance role — no keys on the box) and swapped in just before psycopg2
connects. The value is cached, and the cache is dropped the moment Postgres
rejects a password, so a rotation costs one refused connection instead of a
week-long outage, and needs no redeploy.

Without ``DB_SECRET_ARN`` — local development — nothing here engages.
"""
import json
import logging
import threading
import time

from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Postgres' wording when the password is wrong. Matching on it is what tells a
# rotation apart from an unreachable host, which must NOT invalidate the cache.
_AUTH_FAILURE = "password authentication failed"

_lock = threading.Lock()
_arn = None
_region = None
_ttl = 15 * 60
_client = None
_cached = None  # (monotonic timestamp, {"username": ..., "password": ...})
_listening = False


def _fetch() -> dict:
    """Read the secret. Raises on any boto3/permission/JSON problem."""
    global _client
    if _client is None:
        import boto3

        _client = boto3.client("secretsmanager", region_name=_region)
    data = json.loads(_client.get_secret_value(SecretId=_arn)["SecretString"])
    return {"username": data["username"], "password": data["password"]}


def _credentials():
    """Current master credentials, or ``None`` if they cannot be determined.

    A Secrets Manager outage or a missing IAM grant must not take the app down:
    on failure we keep serving with the last value we read, and if we never read
    one, we return ``None`` so the URL's own password is used unchanged.
    """
    global _cached
    with _lock:
        if _cached is not None and time.monotonic() - _cached[0] < _ttl:
            return _cached[1]
    try:
        creds = _fetch()
    except Exception as exc:  # noqa: BLE001 - any failure degrades the same way
        logger.warning("could not read DB secret %s (%s); using cached/URL password",
                       _arn, exc)
        with _lock:
            return _cached[1] if _cached is not None else None
    with _lock:
        _cached = (time.monotonic(), creds)
    return creds


def invalidate() -> None:
    """Drop the cached password so the next connection re-reads the secret."""
    global _cached
    with _lock:
        _cached = None


def _supply_password(dialect, conn_rec, cargs, cparams):
    """Swap the URL's password for the live one, just before psycopg2 connects.

    Mutates ``cparams`` and returns nothing, which is how ``do_connect`` says
    "carry on and connect normally".
    """
    if not _arn or not dialect.name.startswith("postgres"):
        return
    creds = _credentials()
    # Only touch the account the secret actually describes. A URL pointing at
    # some other user — a read-only role, a local dev database — is left alone.
    if creds is None or cparams.get("user") != creds["username"]:
        return
    cparams["password"] = creds["password"]


def _drop_cache_on_auth_failure(context) -> None:
    """Force a re-read when Postgres rejects the password we supplied.

    In practice this only fires in the minutes after a rotation; dropping the
    cache here is what turns an outage into a single failed request.
    """
    if _arn and _AUTH_FAILURE in str(getattr(context, "original_exception", "") or ""):
        logger.warning("database rejected the password; re-reading %s", _arn)
        invalidate()


def install(app) -> None:
    """Wire the resolver to this app's config. No-op unless DB_SECRET_ARN is set."""
    global _arn, _region, _ttl, _listening
    _arn = app.config.get("DB_SECRET_ARN")
    _region = app.config.get("AWS_REGION")
    _ttl = int(app.config.get("DB_SECRET_TTL") or 15 * 60)
    if not _arn or _listening:
        return
    # Registered on the Engine class, not one engine: Alembic (`flask db
    # upgrade`, which runs on every container start) builds its own.
    event.listen(Engine, "do_connect", _supply_password)
    event.listen(Engine, "handle_error", _drop_cache_on_auth_failure)
    _listening = True
