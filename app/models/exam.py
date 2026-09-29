"""Quizzes (ERD ``exams``): questions, ordered options, graded attempts.

``exam_answers.is_correct`` is the answer key. It never leaves the server for a
question the student has not answered yet — grading happens per answer.
"""
from datetime import datetime

from app.extensions import db


class Exam(db.Model):
    """A quiz attached to a lesson (or a whole module / course)."""

    __tablename__ = "exams"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(
        db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id = db.Column(
        db.Integer, db.ForeignKey("course_topics.id", ondelete="SET NULL"), index=True
    )
    lesson_id = db.Column(
        db.Integer, db.ForeignKey("course_lessons.id", ondelete="SET NULL"), index=True
    )
    name_mn = db.Column(db.String(200), nullable=False)
    name_en = db.Column(db.String(200))
    pass_percent = db.Column(db.Integer, nullable=False, default=70)
    max_attempts = db.Column(db.Integer)          # NULL = unlimited
    is_required = db.Column(db.Boolean, nullable=False, default=True)  # counts for certificate
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    questions = db.relationship(
        "ExamQuestion", back_populates="exam", order_by="ExamQuestion.sort_order",
        passive_deletes=True,
    )


class ExamQuestion(db.Model):
    __tablename__ = "exam_questions"

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(
        db.Integer, db.ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question = db.Column(db.Text, nullable=False)
    explanation = db.Column(db.Text)
    image = db.Column(db.String(500))
    point = db.Column(db.Integer, nullable=False, default=1)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    exam = db.relationship("Exam", back_populates="questions")
    options = db.relationship(
        "ExamOption", back_populates="question", order_by="ExamOption.sort_order",
        passive_deletes=True,
    )


class ExamOption(db.Model):
    """One answer option (ERD ``exam_answers``)."""

    __tablename__ = "exam_answers"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(
        db.Integer, db.ForeignKey("exam_questions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    answer = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    question = db.relationship("ExamQuestion", back_populates="options")


class StudentExam(db.Model):
    """One attempt at a quiz (ERD ``student_exams``). Open while ``completed_at`` is NULL."""

    __tablename__ = "student_exams"
    __table_args__ = (
        # At most one open attempt per student per quiz — resume, never duplicate.
        db.Index("uq_student_exams_open", "exam_id", "student_id", unique=True,
                 postgresql_where=db.text("completed_at IS NULL")),
    )

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(
        db.Integer, db.ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    correct_count = db.Column(db.Integer)
    total = db.Column(db.Integer)
    percent = db.Column(db.Integer)
    is_passed = db.Column(db.Boolean)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)


class StudentExamAnswer(db.Model):
    """The option a student chose for one question in one attempt. Final once written."""

    __tablename__ = "student_exam_answers"
    __table_args__ = (
        db.UniqueConstraint("student_exam_id", "question_id", name="uq_attempt_question"),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_exam_id = db.Column(
        db.Integer, db.ForeignKey("student_exams.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    question_id = db.Column(
        db.Integer, db.ForeignKey("exam_questions.id", ondelete="CASCADE"), nullable=False
    )
    option_id = db.Column(
        db.Integer, db.ForeignKey("exam_answers.id", ondelete="CASCADE"), nullable=False
    )
    is_correct = db.Column(db.Boolean, nullable=False)
    answered_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
