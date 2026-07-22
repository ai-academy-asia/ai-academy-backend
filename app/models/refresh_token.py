from datetime import datetime

from app.extensions import db


class RefreshToken(db.Model):
    """A single refresh token (opaque, DB-backed, rotated on use).

    Only the SHA-256 hash of the token is stored — the raw value is returned to
    the client once and never persisted. Rotation: each successful refresh
    revokes the presented token and links it to its replacement via
    ``replaced_by_id``, so presenting an already-revoked token is detectable as
    reuse (token theft) and triggers revocation of the account's whole family.
    TTL differs per actor_type (see app.auth.refresh.refresh_ttl_for).
    """

    __tablename__ = "refresh_tokens"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer,
        db.ForeignKey("auth_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)
    replaced_by_id = db.Column(db.Integer, db.ForeignKey("refresh_tokens.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    account = db.relationship("AuthAccount", backref=db.backref("refresh_tokens", lazy="dynamic"))

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > datetime.utcnow()

    def __repr__(self) -> str:
        state = "active" if self.is_active else "inactive"
        return f"<RefreshToken {self.id} account={self.account_id} {state}>"
