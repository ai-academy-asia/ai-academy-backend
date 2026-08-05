"""StorePay integration (buy-now-pay-later / consumer loan).

Unlike QPay, StorePay settles a *loan*: the student confirms the purchase inside
the StorePay app and StorePay pays the merchant, collecting from the student over
time. So "create invoice" == "request a loan" and there is no QR — the customer's
registered phone number is the anchor.

Flow
----
1. ``oauth/token``   — password grant, Basic-authed with client id/secret → bearer.
2. ``loan``          — create the loan (amount + customer phone + our reference).
3. StorePay calls our ``callback_url`` on approval/decline; we then
4. ``loan/details``  — confirm the authoritative loan status.

Config keys (``STOREPAY_*``)::

    STOREPAY_BASE_URL       API base            default https://service.storepay.mn
    STOREPAY_AUTH_URL       token base          default = STOREPAY_BASE_URL
    STOREPAY_CLIENT_ID      OAuth client (Basic user)
    STOREPAY_CLIENT_SECRET  OAuth secret (Basic pass)
    STOREPAY_USERNAME       merchant app username (password grant)
    STOREPAY_PASSWORD       merchant app password
    STOREPAY_STORE_ID       merchant store id

NOTE: StorePay assigns exact endpoint paths per merchant contract; the paths here
are the common defaults and can be overridden via the matching ``*_PATH`` config
keys (``STOREPAY_TOKEN_PATH`` / ``STOREPAY_LOAN_PATH`` / ``STOREPAY_DETAILS_PATH``).
"""
from __future__ import annotations

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

# StorePay loan statuses that mean "settled to the merchant".
_PAID_STATUSES = {"CONFIRMED", "PAID", "SUCCESS", "DONE", "COMPLETED"}
_DECLINED_STATUSES = {"REJECTED", "DECLINED", "CANCELLED", "CANCELED", "FAILED"}


class StorePayProvider(PaymentProvider):
    name = "storepay"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config.get("base_url", "https://service.storepay.mn").rstrip("/")
        self.auth_url = (config.get("auth_url") or self.base_url).rstrip("/")
        self.client_id = config.get("client_id")
        self.client_secret = config.get("client_secret")
        self.username = config.get("username")
        self.password = config.get("password")
        self.store_id = config.get("store_id")
        self.token_path = config.get("token_path", "/oauth/token")
        self.loan_path = config.get("loan_path", "/merchant/loan")
        self.details_path = config.get("details_path", "/merchant/loan/details")

    def _require_config(self):
        missing = [
            k for k, v in (
                ("STOREPAY_CLIENT_ID", self.client_id),
                ("STOREPAY_CLIENT_SECRET", self.client_secret),
                ("STOREPAY_USERNAME", self.username),
                ("STOREPAY_PASSWORD", self.password),
                ("STOREPAY_STORE_ID", self.store_id),
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
            "POST", f"{self.auth_url}{self.token_path}",
            params={"grant_type": "password", "username": self.username, "password": self.password},
            auth=(self.client_id, self.client_secret),
        )
        token = data.get("access_token")
        if not token:
            raise PaymentGatewayError(self.name, "auth_failed", detail=data)
        _TOKENS.set(token, float(data.get("expires_in", 3600)))
        return token

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    # ------------------------------------------------------------- invoice
    def create_invoice(self, req: InvoiceRequest) -> InvoiceResult:
        self._require_config()
        phone = req.customer.get("phone")
        if not phone:
            raise PaymentGatewayError(
                self.name, "customer_phone_required",
                detail="StorePay loans are keyed to the customer's registered phone.",
            )
        body = {
            "amount": float(req.amount),
            "description": req.description or req.sender_invoice_no,
            "mobileNumber": str(phone),
            "storeId": self.store_id,
            "callbackUrl": req.callback_url,
            # our reference is echoed back so we can reconcile on callback
            "orderId": req.sender_invoice_no,
        }
        data = self._request(
            "POST", f"{self.base_url}{self.loan_path}", json=body, headers=self._auth_headers()
        )
        if data.get("status") == "Failed" or data.get("error"):
            raise PaymentGatewayError(self.name, "loan_declined", detail=data)
        loan_id = _extract_loan_id(data)
        if not loan_id:
            raise PaymentGatewayError(self.name, "loan_create_failed", detail=data)
        return InvoiceResult(provider_invoice_id=str(loan_id), raw=data)

    # -------------------------------------------------------------- status
    def check_invoice(self, invoice) -> PaymentStatus:
        if not invoice.provider_invoice_id:
            return PaymentStatus.unpaid()
        data = self._request(
            "GET", f"{self.base_url}{self.details_path}/{invoice.provider_invoice_id}",
            headers=self._auth_headers(),
        )
        detail = data.get("value") if isinstance(data.get("value"), dict) else data
        status = str(detail.get("status") or detail.get("loanStatus") or "").upper()
        if status in _DECLINED_STATUSES:
            return PaymentStatus.unpaid(raw=data)
        if status not in _PAID_STATUSES:
            return PaymentStatus.unpaid(raw=data)
        amount = detail.get("amount", invoice.amount)
        return PaymentStatus(
            paid=True,
            provider_payment_id=str(detail.get("id") or invoice.provider_invoice_id),
            amount=Decimal(str(amount)),
            paid_at=None,
            method="loan",
            raw=data,
        )


def _extract_loan_id(data: dict):
    """StorePay wraps the loan id differently across API versions; try each."""
    value = data.get("value")
    if isinstance(value, dict):
        return value.get("id") or value.get("loanId")
    if value not in (None, ""):
        return value
    return data.get("id") or data.get("loanId")
