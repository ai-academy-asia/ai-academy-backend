from datetime import datetime

from app.extensions import db
from app.timeutil import iso

# A Payment row records a *settled* movement of money against an invoice.
#   paid                 — fully settled
#   refunded             — fully refunded afterwards
#   partially_refunded   — part of the amount refunded
PAYMENT_STATUSES = ("paid", "refunded", "partially_refunded")

# How the money actually moved (provider-reported, informational).
PAYMENT_METHODS = ("qr", "card", "loan", "transfer", "other")


class Payment(db.Model):
    """A confirmed settlement against an :class:`~app.models.invoice.Invoice`.

    Created only after a gateway callback / statement match is *verified* — never
    from client input. ``(provider, provider_payment_id)`` is unique so replayed
    callbacks are idempotent (the second insert is skipped, not double-counted).

    Refunds mutate the same row (``refunded_amount`` + status). The pilot refund
    rule — attendance <20% → 50% back, ≥20% → nothing — is captured in
    ``refund_pct_attended`` for the finance audit trail.
    """

    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = db.Column(db.String(20), nullable=False, index=True)  # denormalized from invoice
    provider_payment_id = db.Column(db.String(120), nullable=False)  # gateway's payment/txn id

    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="MNT")
    status = db.Column(db.String(20), nullable=False, default="paid")
    method = db.Column(db.String(20))
    paid_at = db.Column(db.DateTime)

    # --- refunds ---
    refunded_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    refund_pct_attended = db.Column(db.Integer)  # attendance % at refund time (business rule)
    refund_reason = db.Column(db.String(255))    # free text, for the finance audit trail
    refunded_at = db.Column(db.DateTime)

    raw = db.Column(db.JSON)  # verified gateway payload (callback / check / statement row)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    invoice = db.relationship("Invoice", back_populates="payments")

    __table_args__ = (
        db.UniqueConstraint("provider", "provider_payment_id", name="uq_payment_provider_txn"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "invoice_id": self.invoice_id,
            "provider": self.provider,
            "provider_payment_id": self.provider_payment_id,
            "amount": float(self.amount) if self.amount is not None else None,
            "currency": self.currency,
            "status": self.status,
            "method": self.method,
            "paid_at": iso(self.paid_at),
            "refunded_amount": float(self.refunded_amount or 0),
            "refund_pct_attended": self.refund_pct_attended,
            "refund_reason": self.refund_reason,
            "refunded_at": iso(self.refunded_at),
            "created_at": iso(self.created_at),
        }

    def __repr__(self) -> str:
        return f"<Payment {self.id} inv={self.invoice_id} {self.provider} {self.status}>"
