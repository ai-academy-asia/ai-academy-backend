from app.extensions import db
from app.models.base import PersonProfile


class Student(PersonProfile):
    """Student profile. Login credentials live in ``auth_accounts`` (actor_type='student')."""

    __tablename__ = "students"

    birth_date = db.Column(db.Date)
    # kids | adult — derived from birth_date, admin-overridable (see business rules).
    ui_mode = db.Column(db.String(10))
    # Parent is contact-only; no separate parent account/login.
    parent_name = db.Column(db.String(200))
    parent_phone = db.Column(db.String(20))

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["ui_mode"] = self.ui_mode
        return data

    def __repr__(self) -> str:
        return f"<Student {self.id} {self.first_name!r}>"
