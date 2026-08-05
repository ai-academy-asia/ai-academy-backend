from datetime import datetime
from decimal import Decimal

from app.extensions import db

# Installment lifecycle.
#   pending — scheduled, not yet due-settled
#   paid    — settled by a verified Payment
#   overdue — past due_date and still unpaid (set by a periodic sweep / on read)
#   waived  — forgiven by finance (counts as satisfied, but not as paid money)
INSTALLMENT_STATUSES = ("pending", "paid", "overdue", "waived")


class PaymentInstallment(db.Model):
    """One scheduled payment in an enrollment's installment plan (хуваарьт төлбөр).

    The plan itself (deposit %, count, interval) is a course-level rule; this
    table is the materialized schedule — one row per due payment. An
    :class:`~app.models.invoice.Invoice` may target a specific installment so the
    gateway payment settles exactly that row.
    """

    __tablename__ = "payment_installments"

    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(
        db.Integer, db.ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    seq = db.Column(db.Integer, nullable=False)  # 1-based position in the plan
    due_date = db.Column(db.Date)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    paid_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        db.UniqueConstraint("enrollment_id", "seq", name="uq_installment_enrollment_seq"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "enrollment_id": self.enrollment_id,
            "student_id": self.student_id,
            "seq": self.seq,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "amount": float(self.amount) if self.amount is not None else None,
            "status": self.status,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
        }

    def __repr__(self) -> str:
        return f"<PaymentInstallment {self.id} enr={self.enrollment_id} #{self.seq} {self.status}>"


class StudentLedger(db.Model):
    """Per-enrollment receivable summary — the single source of truth for авлага.

    One row per (student, enrollment). ``total_due`` comes from the plan/price,
    ``total_paid`` is recomputed from verified Payments, and ``balance`` is the
    stored roll-up. ``next_due_date`` is the earliest unpaid installment.
    """

    __tablename__ = "student_ledger"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enrollment_id = db.Column(
        db.Integer, db.ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False,
        unique=True, index=True,
    )

    total_due = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total_paid = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    balance = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default="MNT")
    next_due_date = db.Column(db.Date)

    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def recompute_balance(self):
        """Keep ``balance`` = due - paid. Call after mutating due/paid."""
        due = self.total_due or Decimal(0)
        paid = self.total_paid or Decimal(0)
        self.balance = due - paid
        return self.balance

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "student_id": self.student_id,
            "enrollment_id": self.enrollment_id,
            "total_due": float(self.total_due or 0),
            "total_paid": float(self.total_paid or 0),
            "balance": float(self.balance or 0),
            "currency": self.currency,
            "next_due_date": self.next_due_date.isoformat() if self.next_due_date else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<StudentLedger enr={self.enrollment_id} bal={self.balance}>"
