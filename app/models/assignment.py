"""Homework: assignments per cohort, versioned student submissions, uploaded files.

Submissions are never overwritten — each (re)submission is a new ``version`` row,
because homework is archived, not edited (business rule). Mentor feedback lives
on the submission it answers.
"""
from datetime import datetime

from app.extensions import db

SUBMISSION_STATUSES = ("submitted", "reviewed")


class Assignment(db.Model):
    """A task set for one cohort, optionally tied to a lesson (ERD ``assignments``)."""

    __tablename__ = "assignments"

    id = db.Column(db.Integer, primary_key=True)
    cohort_id = db.Column(
        db.Integer, db.ForeignKey("cohorts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lesson_id = db.Column(
        db.Integer, db.ForeignKey("course_lessons.id", ondelete="SET NULL"), index=True
    )
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id", ondelete="SET NULL"))
    title_mn = db.Column(db.String(200), nullable=False)
    title_en = db.Column(db.String(200))
    instructions_mn = db.Column(db.Text)
    instructions_en = db.Column(db.Text)
    due_date = db.Column(db.Date)
    max_score = db.Column(db.Numeric(6, 2))
    attachment_material_id = db.Column(
        db.Integer, db.ForeignKey("lesson_materials.id", ondelete="SET NULL")
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class StudentFile(db.Model):
    """A file a student uploaded (private S3 object), attachable to a submission."""

    __tablename__ = "student_files"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    file_key = db.Column(db.String(500), nullable=False, unique=True)
    file_name = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(120))
    size_bytes = db.Column(db.BigInteger, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class AssignmentSubmission(db.Model):
    """One version of a student's answer to an assignment (ERD ``assignment_submissions``)."""

    __tablename__ = "assignment_submissions"
    __table_args__ = (
        db.UniqueConstraint("assignment_id", "student_id", "version",
                            name="uq_submission_version"),
    )

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(
        db.Integer, db.ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    version = db.Column(db.Integer, nullable=False, default=1)
    submission_url = db.Column(db.String(1000))      # the "link" field
    note = db.Column(db.Text)                        # the "description" field
    file_id = db.Column(db.Integer, db.ForeignKey("student_files.id", ondelete="SET NULL"))
    status = db.Column(db.String(20), nullable=False, default="submitted", index=True)
    score = db.Column(db.Numeric(6, 2))
    feedback = db.Column(db.Text)
    graded_by_teacher_id = db.Column(
        db.Integer, db.ForeignKey("teachers.id", ondelete="SET NULL")
    )
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    graded_at = db.Column(db.DateTime)
