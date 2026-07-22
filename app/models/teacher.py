from app.extensions import db
from app.models.base import PersonProfile


class Teacher(PersonProfile):
    """Teacher profile. Login credentials live in ``auth_accounts`` (actor_type='teacher')."""

    __tablename__ = "teachers"

    bio = db.Column(db.Text)

    def __repr__(self) -> str:
        return f"<Teacher {self.id} {self.first_name!r}>"
