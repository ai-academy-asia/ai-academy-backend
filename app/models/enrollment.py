from datetime import datetime

from app.extensions import db

ENROLLMENT_STATUSES = ("active", "cancelled")


class Enrollment(db.Model):
    """A student's selection of / placement into a cohort (анги). One row per
    (cohort, student). Cancelling keeps the row (status='cancelled') for history."""

    __tablename__ = "enrollments"

    id = db.Column(db.Integer, primary_key=True)
    cohort_id = db.Column(
        db.Integer, db.ForeignKey("cohorts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # ERD parity: denormalized course, progress + provenance.
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id", ondelete="SET NULL"), index=True)
    progress_pct = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), nullable=False, default="active")
    created_via = db.Column(db.String(20))          # web | app | admin
    created_by_admin_id = db.Column(db.Integer)     # staff id when staff-enrolled
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  # ~ enrolled_at
    completed_at = db.Column(db.DateTime)

    cohort = db.relationship("Cohort", back_populates="enrollments")
    student = db.relationship("Student")

    __table_args__ = (
        db.UniqueConstraint("cohort_id", "student_id", name="uq_enrollment_cohort_student"),
    )

    def to_dict(self, with_student: bool = True) -> dict:
        data = {
            "id": self.id,
            "cohort_id": self.cohort_id,
            "student_id": self.student_id,
            "course_id": self.course_id,
            "progress_pct": self.progress_pct,
            "status": self.status,
            "created_via": self.created_via,
            "created_by_admin_id": self.created_by_admin_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        if with_student and self.student is not None:
            s = self.student
            data["student"] = {
                "id": s.id,
                "name": f"{s.first_name} {s.last_name or ''}".strip(),
                "phone": s.phone,
            }
        return data

    def __repr__(self) -> str:
        return (
            f"<Enrollment {self.id} cohort={self.cohort_id} "
            f"student={self.student_id} {self.status}>"
        )
