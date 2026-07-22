from datetime import datetime

from app.extensions import db


class Classroom(db.Model):
    """A physical training room. Per the ERD, the training center is a plain
    ``center_name`` text column here (not a separate Center entity). Managed by
    super_admin only. Bookings/scheduling live elsewhere (out of scope here)."""

    __tablename__ = "classrooms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)      # e.g. "Room 301"
    center_name = db.Column(db.String(200))               # e.g. "AI Academy Central"
    location = db.Column(db.String(255))                  # ERD: address / location text
    capacity = db.Column(db.Integer)
    floor = db.Column(db.String(40))
    equipment = db.Column(db.JSON)                         # list, e.g. ["projector", "30 PCs"]
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        db.UniqueConstraint("center_name", "name", name="uq_classroom_center_name"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "center_name": self.center_name,
            "location": self.location,
            "capacity": self.capacity,
            "floor": self.floor,
            "equipment": self.equipment,
            "is_active": self.is_active,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<Classroom {self.id} {self.name!r} @ {self.center_name!r}>"
