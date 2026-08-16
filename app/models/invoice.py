from datetime import datetime

from app.extensions import db
from app.timeutil import iso

# Which gateway a given invoice is routed through. Kept as a plain string (not an
# enum type) to match the rest of the schema and to add providers without a migration.
INVOICE_PROVIDERS = ("qpay", "storepay", "golomt")

# Lifecycle of a single payment request.
#   pending   — created at the gateway, waiting for the payer
#   paid      — settled (a Payment row exists / callback verified)
#   expired   — gateway invoice timed out
#   cancelled — voided by staff before payment
#   failed    — gateway rejected creation (e.g. StorePay loan declined)
INVOICE_STATUSES = ("pending", "paid", "expired", "cancelled", "failed")


class Invoice(db.Model):
    """A single payment request issued to one of the payment gateways.

    One Invoice == one "please pay X via provider Y" ask. It is the boundary
    object between our money domain (enrollment / installment / ledger) and the
    external gateway. Provider-specific artefacts (QR text, bank deeplinks, the
    gateway's own invoice id) live here so the provider modules stay stateless.

    Settlement produces one or more :class:`~app.models.payment.Payment` rows;
    ``status`` is the denormalized roll-up used by the UI.
    """

    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(20), nullable=False, index=True)  # qpay | storepay | golomt

    # What this invoice is for. All nullable so an invoice can be raised for an
    # ad-hoc charge, but normally it hangs off an enrollment (+ optional installment).
    enrollment_id = db.Column(
        db.Integer, db.ForeignKey("enrollments.id", ondelete="SET NULL"), index=True
    )
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="SET NULL"), index=True
    )
    installment_id = db.Column(
        db.Integer, db.ForeignKey("payment_installments.id", ondelete="SET NULL"), index=True
    )

    # Our own merchant reference — the string we send to the gateway and match on
    # when a callback / bank statement comes back. Globally unique, human-traceable.
    sender_invoice_no = db.Column(db.String(64), nullable=False, unique=True, index=True)

    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="MNT")
    description = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)

    # --- gateway artefacts (filled on create) ---
    # QPay invoice_id / StorePay loanId / Golomt reference
    provider_invoice_id = db.Column(db.String(120), index=True)
    qr_text = db.Column(db.Text)          # raw QR payload (QPay)
    qr_image = db.Column(db.Text)         # base64 PNG (QPay)
    payment_url = db.Column(db.String(500))  # hosted checkout / short link
    urls = db.Column(db.JSON)             # bank deeplink list [{name, link, logo}]
    provider_meta = db.Column(db.JSON)    # raw create response, for audit/debug

    expires_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    payments = db.relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")

    @property
    def is_open(self) -> bool:
        return self.status == "pending"

    def to_dict(self, *, with_qr: bool = True) -> dict:
        data = {
            "id": self.id,
            "provider": self.provider,
            "enrollment_id": self.enrollment_id,
            "student_id": self.student_id,
            "installment_id": self.installment_id,
            "sender_invoice_no": self.sender_invoice_no,
            "amount": float(self.amount) if self.amount is not None else None,
            "currency": self.currency,
            "description": self.description,
            "status": self.status,
            "provider_invoice_id": self.provider_invoice_id,
            "payment_url": self.payment_url,
            "urls": self.urls,
            "expires_at": iso(self.expires_at),
            "paid_at": iso(self.paid_at),
            "created_at": iso(self.created_at),
        }
        if with_qr:
            data["qr_text"] = self.qr_text
            data["qr_image"] = self.qr_image
        return data

    def __repr__(self) -> str:
        return f"<Invoice {self.id} {self.provider} {self.sender_invoice_no} {self.status}>"
