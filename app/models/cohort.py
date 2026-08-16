from datetime import datetime

from app.extensions import db
from app.timeutil import iso

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
    parent_cohort_id = db.Column(
        db.Integer, db.ForeignKey("cohorts.id", ondelete="SET NULL"), index=True
    )
    # Id this run had in the legacy system — unique there, and the key the
    # marketing site books against.
    legacy_schedule_id = db.Column(db.Integer, unique=True, index=True)
    # Legacy course this run sat under. Runs we group into one course did not
    # always share one there (legacy 53 and 57 both fed "Afternoon BootCamp
    # 10–13"), so the course-level id alone would leave some ids unresolvable.
    legacy_course_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String(200), nullable=False)   # e.g. "Corporate Leaders 2026-08"
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    graduation_date = db.Column(db.Date)               # ERD parity

    teacher_id = db.Column(
        db.Integer, db.ForeignKey("teachers.id", ondelete="SET NULL"), index=True
    )
    classroom_id = db.Column(
        db.Integer, db.ForeignKey("classrooms.id", ondelete="SET NULL"), index=True
    )

    capacity = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    # Weekly meeting time (same time on each listed day).
    meeting_days = db.Column(db.JSON)          # e.g. ["mon", "wed"]
    start_time = db.Column(db.String(5))       # "HH:MM"
    end_time = db.Column(db.String(5))         # "HH:MM"
    schedule_note = db.Column(db.Text)  # optional free-text note

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
            "start_date": iso(self.start_date),
            "end_date": iso(self.end_date),
            "graduation_date": iso(self.graduation_date),
            "meeting_days": self.meeting_days,
            "start_time": self.start_time,
            "end_time": self.end_time,
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
            data["created_at"] = iso(self.created_at)
            data["updated_at"] = iso(self.updated_at)
        return data

    def __repr__(self) -> str:
        return f"<Cohort {self.id} {self.name!r} ({self.status})>"


# What a legacy schedule row meant. The old system had no concept of "pay a
# deposit" — it published a second schedule row at a reduced price and let the
# buyer pick that one instead, so the id itself is the payment terms.
LEGACY_SCHEDULE_KINDS = ("full", "deposit", "promo", "promo_deposit")


class CohortLegacySchedule(db.Model):
    """Maps every legacy schedule id the marketing site can send onto a cohort.

    ``Cohort.legacy_schedule_id`` holds only the full-price id, which is all the
    site sends while the buyer leaves the terms alone. Choosing «Урьдчилгаа
    төлөх» or applying the promo code swaps in a different id — up to four per
    run — and those have no cohort of their own: it is the same seat in the same
    class, billed differently.

    ``charge_percent`` is why this is a table and not a set of columns: the
    server has to know what fraction of the price the chosen id stands for, or
    a buyer who picks a 50% deposit gets invoiced 100%.
    """

    __tablename__ = "cohort_legacy_schedules"

    legacy_schedule_id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    cohort_id = db.Column(
        db.Integer, db.ForeignKey("cohorts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    kind = db.Column(db.String(20), nullable=False, default="full")
    charge_percent = db.Column(db.Numeric(5, 2), nullable=False, default=100)

    cohort = db.relationship("Cohort")

    def __repr__(self) -> str:
        return (
            f"<CohortLegacySchedule {self.legacy_schedule_id} -> "
            f"cohort {self.cohort_id} {self.kind} {self.charge_percent}%>"
        )
