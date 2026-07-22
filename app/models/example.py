from datetime import datetime

from app.extensions import db


class Example(db.Model):
    """Placeholder model — proves the DB connection and migrations work.

    Replace with the real AIAA schema (users, courses, enrollments, ...).
    """

    __tablename__ = "examples"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Example {self.id} {self.name!r}>"
