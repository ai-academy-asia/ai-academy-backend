from datetime import datetime

from app.extensions import db

# eBarimt receipt kind. Mirrors PosAPI billType: "1" = individual (B2C),
# "3" = organization (B2B, needs the customer's tax register number).
EBARIMT_TYPES = ("B2C_RECEIPT", "B2B_RECEIPT")

# Lifecycle.
#   temp     — generated locally in temp mode (no real PosAPI merchant rights yet);
#              carries is_temp_mode=True and awaits re-issue to the real PosAPI.
#   issued   — accepted by the real PosAPI (has a DDTD / lottery).
#   returned — voided / refunded at the PosAPI.
#   failed   — PosAPI rejected issuance.
EBARIMT_STATUSES = ("temp", "issued", "returned", "failed")


class EBarimtReceipt(db.Model):
    """A Mongolian tax receipt (НӨАТ-ын баримт) for a settled payment.

    Issued through the eBarimt **PosAPI** (a local REST service from the tax
    authority). Until the merchant's PosAPI rights are live, the system runs in
    **temp mode**: a receipt row is created with ``is_temp_mode=True`` and no real
    DDTD, so the payment flow works end to end and the receipts can be replayed to
    the real PosAPI later (see :func:`app.services.ebarimt.reissue`).
    """

    __tablename__ = "ebarimt_receipts"

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(
        db.Integer, db.ForeignKey("payments.id", ondelete="SET NULL"), index=True
    )
    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoices.id", ondelete="SET NULL"), index=True
    )

    type = db.Column(db.String(20), nullable=False, default="B2C_RECEIPT")
    customer_register = db.Column(db.String(20))  # B2B: buyer org tax register

    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    vat_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    city_tax_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    district_code = db.Column(db.String(10))
    pos_no = db.Column(db.String(40))

    is_temp_mode = db.Column(db.Boolean, nullable=False, default=True, index=True)
    status = db.Column(db.String(20), nullable=False, default="temp", index=True)

    # --- PosAPI artefacts (filled when issued for real) ---
    ebarimt_id = db.Column(db.String(64), index=True)  # DDTD — the receipt id
    lottery = db.Column(db.String(20))                 # сугалааны дугаар
    qr_data = db.Column(db.Text)
    raw = db.Column(db.JSON)  # PosAPI response, or the temp payload we'll replay

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    issued_at = db.Column(db.DateTime)
    returned_at = db.Column(db.DateTime)

    # Delivery state, separate from tax state: a receipt can be validly issued
    # and still not have reached the buyer. The public /payments/receipt endpoint
    # reports exactly this, and finance needs to see what failed to send.
    emailed_at = db.Column(db.DateTime)
    emailed_to = db.Column(db.String(255))
    email_error = db.Column(db.String(500))

    payment = db.relationship("Payment")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "payment_id": self.payment_id,
            "invoice_id": self.invoice_id,
            "type": self.type,
            "customer_register": self.customer_register,
            "total_amount": float(self.total_amount) if self.total_amount is not None else None,
            "vat_amount": float(self.vat_amount or 0),
            "city_tax_amount": float(self.city_tax_amount or 0),
            "district_code": self.district_code,
            "pos_no": self.pos_no,
            "is_temp_mode": self.is_temp_mode,
            "status": self.status,
            "ebarimt_id": self.ebarimt_id,
            "lottery": self.lottery,
            "qr_data": self.qr_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "returned_at": self.returned_at.isoformat() if self.returned_at else None,
            "emailed_at": self.emailed_at.isoformat() if self.emailed_at else None,
            "emailed_to": self.emailed_to,
            "email_error": self.email_error,
        }

    def __repr__(self) -> str:
        tag = "temp" if self.is_temp_mode else (self.ebarimt_id or self.status)
        return f"<EBarimtReceipt {self.id} pay={self.payment_id} {tag}>"
