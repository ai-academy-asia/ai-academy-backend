from app.extensions import db
from app.models.base import PersonProfile

# Admin RBAC roles (staff only). Teachers/students are not staff.
STAFF_ROLES = (
    "super_admin",
    "finance",
    "sales_enrollment",
    "content_marketing",
)


class Staff(PersonProfile):
    """Back-office staff profile. Login credentials live in ``auth_accounts``
    (actor_type='staff'); the specific admin role is stored here and mirrored
    onto the auth account for RBAC checks."""

    __tablename__ = "staff"

    role = db.Column(db.String(40), nullable=False, default="super_admin")

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["role"] = self.role
        return data

    def __repr__(self) -> str:
        return f"<Staff {self.id} {self.first_name!r} ({self.role})>"
