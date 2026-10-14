"""Firebase Cloud Messaging HTTP v1 — one message per device token (issue #2).

``FCM_CREDENTIALS`` is a Firebase service account: its JSON, or a path to the
JSON file. The OAuth2 access token comes from the service account's JWT grant
(RS256 — PyJWT with ``cryptography``) and is cached until a minute before it
expires. Nothing secret is ever logged: no token, key or device token.

Devices are addressed by ``message.token``. FCM marks that field deprecated
in favour of ``fid``, but it still takes registration tokens — which is what
the app's ``firebase_messaging`` hands out. Move to ``fid`` with the client.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import jwt
import requests

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
_REQUIRED = ("project_id", "client_email", "private_key")
# Keys FCM rejects in `data` ("from", "message_type", "google.*", "gcm.notification.*").
_RESERVED = ("from", "message_type")
_RESERVED_PREFIXES = ("google.", "gcm.notification.")

SENT, UNREGISTERED, FAILED = "sent", "unregistered", "failed"


class FcmError(Exception):
    """Unusable credentials, or no access token — nothing can be sent."""


def http_post(url, **kwargs):
    """The one outbound call. Tests replace it; nothing else here does I/O."""
    return requests.post(url, **kwargs)


def load_credentials(raw) -> dict:
    """The service account from ``FCM_CREDENTIALS`` — JSON text or a file path."""
    text = str(raw).strip()
    if not text.startswith("{"):
        text = Path(text).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except ValueError:
        raise FcmError("credentials are not JSON") from None
    if not isinstance(data, dict) or any(not data.get(k) for k in _REQUIRED):
        raise FcmError("credentials lack project_id, client_email or private_key")
    return data


_cache = {"token": None, "expires": 0.0, "email": None}
_lock = threading.Lock()


def reset_cache() -> None:
    with _lock:
        _cache.update(token=None, expires=0.0, email=None)


def access_token(creds, *, timeout, now=None) -> str:
    """A cached OAuth2 access token for ``creds``; fetched when missing or due."""
    now = time.time() if now is None else now
    with _lock:
        if (_cache["token"] and _cache["email"] == creds["client_email"]
                and now < _cache["expires"] - 60):
            return _cache["token"]
        assertion = jwt.encode(
            {"iss": creds["client_email"], "scope": SCOPE, "aud": TOKEN_URL,
             "iat": int(now), "exp": int(now) + 3600},
            creds["private_key"], algorithm="RS256",
        )
        resp = http_post(TOKEN_URL, timeout=timeout, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        })
        body = _json(resp)
        token = body.get("access_token")
        if resp.status_code != 200 or not isinstance(token, str):
            raise FcmError(f"token request answered HTTP {resp.status_code}")
        expires_in = body.get("expires_in")
        _cache.update(token=token, email=creds["client_email"],
                      expires=now + (expires_in if isinstance(expires_in, int) else 3600))
        return token


def message(device_token, *, title, body=None, data=None) -> dict:
    """The v1 send body: the visible text, `data` as strings, Android high
    priority and the default APNs sound."""
    notification = {"title": title}
    if body:
        notification["body"] = body
    payload = {
        str(k): _string(v) for k, v in (data or {}).items()
        if v is not None and k not in _RESERVED and not str(k).startswith(_RESERVED_PREFIXES)
    }
    return {"message": {
        "token": device_token,
        "notification": notification,
        "data": payload,
        "android": {"priority": "HIGH"},
        "apns": {"payload": {"aps": {"sound": "default"}}},
    }}


def send(creds, body, *, timeout) -> str:
    """POST one message: ``SENT``, ``UNREGISTERED`` (the token is dead) or ``FAILED``.

    Only FCM's own ``UNREGISTERED`` error code marks a token dead — a bare 404
    (a wrong project, say) does not, so a misconfiguration never deletes tokens.
    """
    resp = http_post(
        SEND_URL.format(project_id=creds["project_id"]), json=body, timeout=timeout,
        headers={"Authorization": f"Bearer {access_token(creds, timeout=timeout)}"},
    )
    if 200 <= resp.status_code < 300:
        return SENT
    code = error_code(resp)
    if code == "UNREGISTERED":
        return UNREGISTERED
    if resp.status_code == 401:
        reset_cache()       # a revoked or expired access token: fetch anew next time
    log.warning("fcm send failed: HTTP %s %s", resp.status_code, code or "")
    return FAILED


def error_code(resp) -> str | None:
    """The FCM ``errorCode`` of an error body (``error.details[].errorCode``)."""
    error = _json(resp).get("error")
    if not isinstance(error, dict):
        return None
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and isinstance(detail.get("errorCode"), str):
            return detail["errorCode"]
    return None


def _json(resp) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _string(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
