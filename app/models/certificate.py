"""Certificates issued to students, and the one-time codes behind password resets."""
from datetime import datetime

from app.extensions import db
from app.timeutil import iso


class Certificate(db.Model):
    """A course completion certificate issued to one student (ERD ``certificates``).

    Archived, never deleted (business rule). ``file_key`` is the private S3 object
    of the rendered certificate; ``verify_url`` is the public check page.
    """

    __tablename__ = "certificates"
    __table_args__ = (
        db.UniqueConstraint("student_id", "course_id", name="uq_certificate_student_course"),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    course_id = db.Column(
        db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enrollment_id = db.Column(
        db.Integer, db.ForeignKey("enrollments.id", ondelete="SET NULL")
    )
    cert_number = db.Column(db.String(40), nullable=False, unique=True)
    file_key = db.Column(db.String(500))
    verify_url = db.Column(db.String(500))
    payment_cleared = db.Column(db.Boolean, nullable=False, default=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    issued_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    student = db.relationship("Student")
    course = db.relationship("Course")

    @property
    def student_name(self):
        s = self.student
        return f"{s.first_name} {s.last_name or ''}".strip() if s is not None else None

    @property
    def course_title(self):
        c = self.course
        return {"mn": c.title_mn, "en": c.title_en} if c is not None else None

    def to_student_dict(self) -> dict:
        """What the student app sees (§2.9 ``certificate``)."""
        return {
            "cert_number": self.cert_number,
            "issued_at": iso(self.issued_at),
            "verify_url": self.verify_url,
            "has_file": bool(self.file_key),
        }

    def to_dict(self) -> dict:
        """Staff view."""
        data = self.to_student_dict()
        data.update({
            "id": self.id,
            "student_id": self.student_id,
            "student_name": self.student_name,
            "course_id": self.course_id,
            "course_title": self.course_title,
            "enrollment_id": self.enrollment_id,
            "payment_cleared": self.payment_cleared,
            "is_archived": self.is_archived,
        })
        return data

    def to_verify_dict(self) -> dict:
        """The public verification answer — nothing beyond what the paper shows."""
        return {
            "valid": True,
            "cert_number": self.cert_number,
            "student_name": self.student_name,
            "course_title": self.course_title,
            "issued_at": iso(self.issued_at),
        }


class OtpVerification(db.Model):
    """A one-time code (ERD ``otp_verifications``), stored only as a hash."""

    __tablename__ = "otp_verifications"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer, db.ForeignKey("auth_accounts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    purpose = db.Column(db.String(30), nullable=False, default="password_reset")
    code_hash = db.Column(db.String(128), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
