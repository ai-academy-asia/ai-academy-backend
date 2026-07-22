from datetime import datetime

from app.extensions import db

# draft = not visible; open = accepting enrollment; closed = not accepting.
COHORT_STATUSES = ("draft", "open", "closed")


class Cohort(db.Model):
    """A scheduled run (анги) of a course: a date range with an assigned teacher
    and classroom. Students enroll into it. The teacher's / classroom's schedule
    is simply the set of cohorts they are assigned to (date-range based; no
    per-day sessions). A teacher or classroom may not be double-booked across
    overlapping date ranges — enforced in the route layer."""

    __tablename__ = "cohorts"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(
        db.Integer, db.ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # ERD: sub-cohort support (e.g. Bootcamp's parallel classes).
    parent_cohort_id = db.Column(db.Integer, db.ForeignKey("cohorts.id", ondelete="SET NULL"), index=True)
    name = db.Column(db.String(200), nullable=False)   # e.g. "Corporate Leaders 2026-08"
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    graduation_date = db.Column(db.Date)               # ERD parity

    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id", ondelete="SET NULL"), index=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id", ondelete="SET NULL"), index=True)

    capacity = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    schedule_note = db.Column(db.Text)  # free-text meeting times (e.g. "Mon/Wed 18:00-20:00")

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    course = db.relationship("Course")
    teacher = db.relationship("Teacher")
    classroom = db.relationship("Classroom")
    enrollments = db.relationship(
        "Enrollment", back_populates="cohort", passive_deletes=True
    )

    @property
    def is_public(self) -> bool:
        return self.status in ("open", "closed")

    @property
    def enrolled_count(self) -> int:
        from app.models import Enrollment

        return Enrollment.query.filter_by(cohort_id=self.id, status="active").count()

    @property
    def seats_available(self):
        if self.capacity is None:
            return None
        return max(self.capacity - self.enrolled_count, 0)

    def to_dict(self, detail: bool = False) -> dict:
        teacher = self.teacher
        classroom = self.classroom
        course = self.course
        data = {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "course_id": self.course_id,
            "course": {
                "id": course.id,
                "slug": course.slug,
                "title_mn": course.title_mn,
                "title_en": course.title_en,
            } if course else None,
            "parent_cohort_id": self.parent_cohort_id,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "graduation_date": self.graduation_date.isoformat() if self.graduation_date else None,
            "schedule_note": self.schedule_note,
            "capacity": self.capacity,
            "enrolled_count": self.enrolled_count,
            "seats_available": self.seats_available,
            "teacher": {
                "id": teacher.id,
                "name": f"{teacher.first_name} {teacher.last_name or ''}".strip(),
            } if teacher else None,
            "classroom": {
                "id": classroom.id,
                "name": classroom.name,
                "center_name": classroom.center_name,
            } if classroom else None,
        }
        if detail:
            data["created_at"] = self.created_at.isoformat() if self.created_at else None
            data["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
        return data

    def __repr__(self) -> str:
        return f"<Cohort {self.id} {self.name!r} ({self.status})>"
