"""Course content a student works through: modules, lessons, materials, progress, notes.

Names follow the ERD: a *module* in the app is a ``course_topics`` row, a
*lesson* is ``course_lessons``. Content belongs to the course; materials may be
narrowed to one cohort; progress and notes belong to the student.
"""
from datetime import datetime

from app.extensions import db

LESSON_TYPES = ("recording", "video", "reading")
MATERIAL_TYPES = ("file", "link")


class CourseTopic(db.Model):
    """A module of a course (ERD ``course_topics``)."""

    __tablename__ = "course_topics"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(
        db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name_mn = db.Column(db.String(200), nullable=False)
    name_en = db.Column(db.String(200))
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    lessons = db.relationship(
        "CourseLesson", back_populates="topic", order_by="CourseLesson.sort_order",
        passive_deletes=True,
    )


class CourseLesson(db.Model):
    """A lesson inside a module (ERD ``course_lessons``)."""

    __tablename__ = "course_lessons"

    id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(
        db.Integer, db.ForeignKey("course_topics.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name_mn = db.Column(db.String(200), nullable=False)
    name_en = db.Column(db.String(200))
    type = db.Column(db.String(20), nullable=False, default="recording")
    classroom_embed_url = db.Column(db.String(500))   # video/recording embed
    duration_seconds = db.Column(db.Integer)
    summary_mn = db.Column(db.Text)
    summary_en = db.Column(db.Text)
    # [{title:{mn,en}, body:{mn,en}, bullets:[{mn,en}]}] — the structure the app renders.
    sections = db.Column(db.JSON)
    is_preview = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    topic = db.relationship("CourseTopic", back_populates="lessons")


class LessonMaterial(db.Model):
    """A downloadable file or external link attached to a lesson.

    ``cohort_id`` NULL = shown to every cohort of the course; set = that cohort only.
    Files live privately on S3 (``file_key``); links carry ``url``.
    """

    __tablename__ = "lesson_materials"

    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(
        db.Integer, db.ForeignKey("course_lessons.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    cohort_id = db.Column(
        db.Integer, db.ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    uploaded_by_account_id = db.Column(
        db.Integer, db.ForeignKey("auth_accounts.id", ondelete="SET NULL")
    )
    title = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(10), nullable=False, default="file")
    url = db.Column(db.String(1000))
    file_key = db.Column(db.String(500))
    file_name = db.Column(db.String(255))
    content_type = db.Column(db.String(120))
    size_bytes = db.Column(db.BigInteger)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class LessonProgress(db.Model):
    """Whether one enrollment has completed one lesson (ERD ``lesson_progress``)."""

    __tablename__ = "lesson_progress"
    __table_args__ = (
        db.UniqueConstraint("enrollment_id", "lesson_id", name="uq_lesson_progress"),
    )

    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(
        db.Integer, db.ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    lesson_id = db.Column(
        db.Integer, db.ForeignKey("course_lessons.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    completed = db.Column(db.Boolean, nullable=False, default=False)
    watched_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)


class LessonNote(db.Model):
    """A student's own note on a lesson — one per student per lesson."""

    __tablename__ = "lesson_notes"
    __table_args__ = (
        db.UniqueConstraint("student_id", "lesson_id", name="uq_lesson_note"),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    lesson_id = db.Column(
        db.Integer, db.ForeignKey("course_lessons.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
