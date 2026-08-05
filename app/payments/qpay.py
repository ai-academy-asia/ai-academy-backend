"""QPay v2 gateway integration (QR / bank-deeplink e-payment).

Flow
----
1. ``auth/token``      — Basic-auth with merchant username/password → bearer token
   (cached, refreshed via ``refresh_token`` or re-login on expiry).
2. ``invoice``         — create an invoice; QPay returns a QR + per-bank deeplinks.
3. QPay POSTs our ``callback_url`` when the payer pays; we then call
4. ``payment/check``   — the authoritative "was this invoice paid?" query.

Config keys (``QPAY_*`` in app config)::

    QPAY_BASE_URL      default https://merchant.qpay.mn
    QPAY_USERNAME      merchant API username
    QPAY_PASSWORD      merchant API password
    QPAY_INVOICE_CODE  merchant invoice template code (from QPay onboarding)

Docs: https://developer.qpay.mn (v2). Endpoint paths below match the v2 API.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .base import (
    InvoiceRequest,
    InvoiceResult,
    PaymentGatewayError,
    PaymentProvider,
    PaymentStatus,
    _TokenCache,
)

_TOKENS = _TokenCache()


class QPayProvider(PaymentProvider):
    name = "qpay"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config.get("base_url", "https://merchant.qpay.mn").rstrip("/")
        self.username = config.get("username")
        self.password = config.get("password")
        self.invoice_code = config.get("invoice_code")

    def _require_config(self):
        missing = [
            k for k, v in (
                ("QPAY_USERNAME", self.username),
                ("QPAY_PASSWORD", self.password),
                ("QPAY_INVOICE_CODE", self.invoice_code),
            ) if not v
        ]
        if missing:
            raise PaymentGatewayError(self.name, "not_configured", detail={"missing": missing})

    # ---------------------------------------------------------------- auth
    def _token(self) -> str:
        cached = _TOKENS.get()
        if cached:
            return cached
        self._require_config()
        data = self._request(
            "POST", f"{self.base_url}/v2/auth/token",
            auth=(self.username, self.password),
            headers={"Content-Type": "application/json"},
        )
        token = data.get("access_token")
        if not token:
            raise PaymentGatewayError(self.name, "auth_failed", detail=data)
        # QPay tokens live ~ expires_in seconds; default to 1h if absent.
        _TOKENS.set(token, float(data.get("expires_in", 3600)))
        return token

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    # ------------------------------------------------------------- invoice
    def create_invoice(self, req: InvoiceRequest) -> InvoiceResult:
        self._require_config()
        # Phone, never `register`: that is the buyer's national ID number, and
        # this field is echoed back and persisted in provider_meta. Nothing
        # downstream needs it — the B2C receipt path drops it too.
        receiver = req.customer.get("phone") or req.sender_invoice_no or "terminal"
        body = {
            "invoice_code": self.invoice_code,
            "sender_invoice_no": req.sender_invoice_no,
            "invoice_receiver_code": str(receiver),
            "invoice_description": req.description or req.sender_invoice_no,
            "amount": float(req.amount),
            "callback_url": req.callback_url,
        }
        data = self._request(
            "POST", f"{self.base_url}/v2/invoice", json=body, headers=self._auth_headers()
        )
        invoice_id = data.get("invoice_id")
        if not invoice_id:
            raise PaymentGatewayError(self.name, "invoice_create_failed", detail=data)
        return InvoiceResult(
            provider_invoice_id=invoice_id,
            qr_text=data.get("qr_text"),
            qr_image=data.get("qr_image"),
            payment_url=data.get("qPay_shortUrl") or data.get("short_url"),
            urls=data.get("urls"),
            raw=data,
        )

    # -------------------------------------------------------------- status
    def check_invoice(self, invoice) -> PaymentStatus:
        if not invoice.provider_invoice_id:
            return PaymentStatus.unpaid()
        body = {
            "object_type": "INVOICE",
            "object_id": invoice.provider_invoice_id,
            "offset": {"page_number": 1, "page_limit": 100},
        }
        data = self._request(
            "POST", f"{self.base_url}/v2/payment/check", json=body, headers=self._auth_headers()
        )
        rows = data.get("rows") or []
        paid_rows = [r for r in rows if str(r.get("payment_status")).upper() == "PAID"]
        if not paid_rows:
            return PaymentStatus.unpaid(raw=data)
        row = paid_rows[0]
        paid_amount = data.get("paid_amount")
        if paid_amount is None:
            paid_amount = row.get("payment_amount", invoice.amount)
        return PaymentStatus(
            paid=True,
            provider_payment_id=str(row.get("payment_id")),
            amount=Decimal(str(paid_amount)),
            paid_at=_parse_dt(row.get("payment_date")),
            method="qr",
            raw=data,
        )


def _parse_dt(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(str(value)[:26], fmt)
        except ValueError:
            continue
    return None
