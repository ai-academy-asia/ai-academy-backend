"""JWT encode/decode helpers."""
from datetime import datetime, timedelta, timezone

import jwt
from flask import current_app


def create_access_token(account) -> str:
    """Issue a signed access token for an AuthAccount."""
    now = datetime.now(timezone.utc)
    ttl = current_app.config["JWT_ACCESS_TTL"]
    payload = {
        "sub": str(account.id),
        "actor_type": account.actor_type,
        "actor_id": account.actor_id,
        "role": account.role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(
        payload,
        current_app.config["JWT_SECRET"],
        algorithm=current_app.config["JWT_ALGORITHM"],
    )


def decode_token(token: str) -> dict:
    """Decode + verify a token. Raises jwt.InvalidTokenError (or a subclass such
    as jwt.ExpiredSignatureError) on any problem."""
    return jwt.decode(
        token,
        current_app.config["JWT_SECRET"],
        algorithms=[current_app.config["JWT_ALGORITHM"]],
    )
