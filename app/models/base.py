from datetime import datetime

from app.extensions import db


class PersonProfile(db.Model):
    """Abstract base for the per-actor profile tables (students / teachers /
    staff). Concrete-table inheritance: each subclass gets its own table with
    these shared columns plus whatever it adds. No table of its own."""

    __abstract__ = True

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "phone": self.phone,
        }
