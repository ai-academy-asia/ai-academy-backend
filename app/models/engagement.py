"""Class sessions and attendance, push tokens, in-app notifications.

A cohort meets on dated sessions (ERD ``class_sessions``); attendance is taken per
session, by the student scanning the teacher's rotating QR or by the teacher
marking it by hand. A session may be tied to the module (topic) it covers — that
is also what dates a module on the student's learning path.
"""
from datetime import datetime

from app.extensions import db

ATTENDANCE_STATUSES = ("present", "late", "absent", "excused")
ATTENDANCE_METHODS = ("qr", "manual")
PUSH_PLATFORMS = ("ios", "android", "web")


class ClassSession(db.Model):
    __tablename__ = "class_sessions"
    __table_args__ = (
        db.UniqueConstraint("cohort_id", "session_date", "start_time",
                            name="uq_class_session_slot"),
    )

    id = db.Column(db.Integer, primary_key=True)
    cohort_id = db.Column(
        db.Integer, db.ForeignKey("cohorts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id = db.Column(
        db.Integer, db.ForeignKey("course_topics.id", ondelete="SET NULL"), index=True
    )
    session_date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.String(5))     # "HH:MM", Asia/Ulaanbaatar
    end_time = db.Column(db.String(5))
    # Rotating check-in code: only its hash is stored, like refresh tokens.
    qr_token_hash = db.Column(db.String(64), index=True)
    qr_expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Attendance(db.Model):
    __tablename__ = "attendance"
    __table_args__ = (
        db.UniqueConstraint("class_session_id", "student_id", name="uq_attendance"),
    )

    id = db.Column(db.Integer, primary_key=True)
    class_session_id = db.Column(
        db.Integer, db.ForeignKey("class_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    status = db.Column(db.String(20), nullable=False, default="present")
    method = db.Column(db.String(20), nullable=False, default="qr")
    marked_by_teacher_id = db.Column(
        db.Integer, db.ForeignKey("teachers.id", ondelete="SET NULL")
    )
    checked_in_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class FirebaseToken(db.Model):
    """A device's push token (ERD ``firebase_tokens``). One token = one device."""

    __tablename__ = "firebase_tokens"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer, db.ForeignKey("auth_accounts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    token = db.Column(db.String(512), nullable=False, unique=True)
    platform = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Notification(db.Model):
    """An in-app notification for one account (ERD ``notifications``)."""

    __tablename__ = "notifications"
    __table_args__ = (db.Index("ix_notifications_account_read", "account_id", "read_at"),)

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer, db.ForeignKey("auth_accounts.id", ondelete="CASCADE"), nullable=False
    )
    kind = db.Column(db.String(40), nullable=False, default="general")
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    data = db.Column(db.JSON)
    read_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
