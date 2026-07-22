from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db

# Actor types — which profile table this account points at.
ACTOR_STUDENT = "student"
ACTOR_TEACHER = "teacher"
ACTOR_STAFF = "staff"
ACTOR_TYPES = (ACTOR_STUDENT, ACTOR_TEACHER, ACTOR_STAFF)

# Explicit, portable hashing method. Werkzeug's default (scrypt) depends on the
# OpenSSL build and is unavailable on some Python builds; pbkdf2 works everywhere.
_PASSWORD_HASH_METHOD = "pbkdf2:sha256"


class AuthAccount(db.Model):
    """Central credential/identity record.

    One row per login. Profile data lives in the per-actor tables
    (``students`` / ``teachers`` / ``staff``); this table owns only the things
    needed to authenticate and authorize: email, password hash, and the RBAC
    role. ``actor_type`` + ``actor_id`` is a polymorphic pointer to the profile
    row (no DB-level FK because it spans three tables — integrity is enforced in
    the service layer plus the (actor_type, actor_id) unique constraint).
    """

    __tablename__ = "auth_accounts"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    actor_type = db.Column(db.String(20), nullable=False)
    actor_id = db.Column(db.Integer, nullable=False)
    # For student/teacher this equals actor_type; for staff it is the admin role
    # (super_admin / finance / sales_enrollment / content_marketing).
    role = db.Column(db.String(40), nullable=False)

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # Per business rule: first login (temp password) must force a change.
    must_change_password = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        db.UniqueConstraint("actor_type", "actor_id", name="uq_auth_actor"),
    )

    # --- email helpers ---
    @staticmethod
    def normalize_email(email: str) -> str:
        return (email or "").strip().lower()

    @classmethod
    def get_by_email(cls, email: str):
        """Look up an account by (normalized) email, or None."""
        return cls.query.filter_by(email=cls.normalize_email(email)).first()

    # --- password helpers ---
    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(
            raw_password, method=_PASSWORD_HASH_METHOD
        )

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    # --- profile lookup ---
    @property
    def profile(self):
        """Return the linked profile row (Student/Teacher/Staff) or None."""
        from app.models import get_profile_model

        model = get_profile_model(self.actor_type)
        if model is None:
            return None
        return db.session.get(model, self.actor_id)

    def to_dict(self, include_profile: bool = True) -> dict:
        data = {
            "id": self.id,
            "email": self.email,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "role": self.role,
            "must_change_password": self.must_change_password,
            "is_active": self.is_active,
        }
        if include_profile:
            profile = self.profile
            data["profile"] = profile.to_dict() if profile is not None else None
        return data

    def __repr__(self) -> str:
        return f"<AuthAccount {self.id} {self.email!r} {self.actor_type}:{self.actor_id}>"
