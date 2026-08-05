"""A gateway that always says "paid" — for demoing the flow without a gateway.

QPay and StorePay need merchant credentials we do not have yet, which blocks
everything downstream: seat settlement, the ledger, and the eBarimt receipt.
This provider stands in for them so the rest can be exercised end to end,
including a real DDTD from the tax authority's staging PosAPI.

**It settles without money.** Enabling it in production would sell courses for
nothing and file tax receipts for payments that never arrived, so it is off by
default, refuses to load against the production API host, and stamps
``sandbox: true`` on everything it returns.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .base import InvoiceRequest, InvoiceResult, PaymentProvider, PaymentStatus


class SandboxProvider(PaymentProvider):
    """Creates an invoice that is already settled."""

    name = "sandbox"

    def create_invoice(self, req: InvoiceRequest) -> InvoiceResult:
        # The UI draws a QR from qr_text; give it something scannable that says
        # plainly what it is, so a screenshot can never be mistaken for a real
        # payment request.
        ref = req.sender_invoice_no
        return InvoiceResult(
            provider_invoice_id=f"SANDBOX-{ref}",
            qr_text=f"SANDBOX|{ref}|{req.amount}|{req.currency}|NOT-A-REAL-PAYMENT",
            payment_url=None,
            urls=[],
            raw={"sandbox": True, "note": "settled without a real payment"},
        )

    def check_invoice(self, invoice) -> PaymentStatus:
        return PaymentStatus(
            paid=True,
            provider_payment_id=f"SANDBOX-TXN-{invoice.id}",
            amount=Decimal(str(invoice.amount)),
            paid_at=datetime.utcnow(),
            method="qr",
            raw={"sandbox": True},
        )

    def verify_callback(self, invoice, payload: dict, headers: dict) -> PaymentStatus:
        return self.check_invoice(invoice)
