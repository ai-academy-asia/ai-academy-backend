"""Test doubles shared across the suite."""


class FakeProvider:
    """Stands in for QPay / StorePay / Golomt. Tests flip ``paid`` / ``fail``."""

    def __init__(self, name):
        from decimal import Decimal

        self.name = name
        self.paid = False
        self.fail = None          # a PaymentGatewayError to raise, or None
        self.amount = None        # override the settled amount (default: invoice amount)
        self.created = []
        self.statement = []       # rows returned by Golomt reconcile, if asked
        self._Decimal = Decimal

    def create_invoice(self, req):
        from app.payments import InvoiceResult

        if self.fail:
            raise self.fail
        self.created.append(req)
        return InvoiceResult(
            provider_invoice_id=f"{self.name.upper()}-{req.sender_invoice_no}",
            qr_text=f"QR|{req.sender_invoice_no}", qr_image="aW1n",
            payment_url=f"https://pay.test/{req.sender_invoice_no}", urls=[],
            raw={"fake": True},
        )

    def check_invoice(self, invoice):
        from datetime import datetime

        from app.payments import PaymentStatus

        if self.fail:
            raise self.fail
        if not self.paid:
            return PaymentStatus.unpaid()
        amount = self.amount if self.amount is not None else invoice.amount
        return PaymentStatus(
            paid=True, provider_payment_id=f"TXN-{invoice.id}",
            amount=self._Decimal(str(amount)), paid_at=datetime.utcnow(), method="qr",
            raw={"fake": True},
        )

    def verify_callback(self, invoice, payload, headers):
        return self.check_invoice(invoice)

    def __getattr__(self, item):
        raise AttributeError(f"FakeProvider({self.name}) has no {item!r}; stub it in the test")
