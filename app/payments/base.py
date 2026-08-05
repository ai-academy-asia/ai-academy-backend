"""Provider-agnostic contract every payment gateway module implements.

Each provider (QPay, StorePay, Golomt Corporate) is a self-contained class that
knows *only* how to talk to its gateway — it never touches the DB or Flask. The
service layer (``app.services.payments``) drives them and persists the result.

Design notes
------------
- Providers take a plain ``config`` dict (built from Flask config in the registry)
  so they can be unit-tested without an app context.
- Money is passed around as :class:`decimal.Decimal`; callers convert to/from the
  DB ``Numeric`` columns.
- Providers raise :class:`PaymentGatewayError` on any gateway failure; the service
  layer maps that onto the HTTP ``ServiceError`` used by the rest of the app.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.httpjson import request_json


class PaymentGatewayError(Exception):
    """A gateway call failed (network, auth, validation, or business decline).

    ``provider`` and ``detail`` are surfaced to finance staff for debugging;
    ``retriable`` hints whether re-issuing the same request might succeed.
    """

    def __init__(self, provider: str, message: str, *, detail=None, retriable: bool = False):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.message = message
        self.detail = detail
        self.retriable = retriable


# --------------------------------------------------------------------------- DTOs
@dataclass
class InvoiceRequest:
    """Everything a gateway needs to raise a payment request."""

    sender_invoice_no: str          # our unique merchant reference
    amount: Decimal
    currency: str
    description: str
    callback_url: str
    customer: dict = field(default_factory=dict)  # {name, phone, email, register}
    extra: dict = field(default_factory=dict)      # provider hints (e.g. Golomt course routing)


@dataclass
class InvoiceResult:
    """Gateway artefacts returned when an invoice is created."""

    provider_invoice_id: str | None = None
    qr_text: str | None = None
    qr_image: str | None = None
    payment_url: str | None = None
    urls: list | None = None
    expires_at: datetime | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class PaymentStatus:
    """Normalized settlement state for one invoice, as reported by the gateway."""

    paid: bool
    provider_payment_id: str | None = None
    amount: Decimal | None = None
    paid_at: datetime | None = None
    method: str | None = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def unpaid(cls, raw=None) -> PaymentStatus:
        return cls(paid=False, raw=raw or {})


# ------------------------------------------------------------------- base class
class PaymentProvider:
    """Base class. Subclasses implement the three lifecycle methods below."""

    name: str = "base"

    def __init__(self, config: dict):
        self.config = config
        self.timeout = int(config.get("timeout", 20))

    # -- lifecycle ---------------------------------------------------------
    def create_invoice(self, req: InvoiceRequest) -> InvoiceResult:
        raise NotImplementedError

    def check_invoice(self, invoice) -> PaymentStatus:
        """Poll the gateway for the current settlement state of ``invoice``."""
        raise NotImplementedError

    def verify_callback(self, invoice, payload: dict, headers: dict) -> PaymentStatus:
        """Validate an inbound webhook and return the settlement it confirms.

        Default: never trust the callback body — re-check with the gateway.
        Providers that sign their callbacks may override to verify locally.
        """
        return self.check_invoice(invoice)

    # -- small HTTP helper shared by subclasses ----------------------------
    def _fail(self, code: str, detail, retriable: bool) -> PaymentGatewayError:
        return PaymentGatewayError(
            self.name, f"gateway_{code}", detail=detail, retriable=retriable
        )

    def _request(self, method: str, url: str, **kwargs) -> dict:
        return request_json(
            method, url, timeout=self.timeout, fail=self._fail, **kwargs
        )


class _TokenCache:
    """Tiny in-process bearer-token cache with expiry (shared by QPay/StorePay).

    Good enough for a single gunicorn worker set; each worker keeps its own copy
    and refreshes independently. Not persisted — a restart just re-authenticates.
    """

    def __init__(self):
        self._token = None
        self._expires_at = 0.0

    def get(self):
        if self._token and time.time() < self._expires_at - 30:  # 30s safety margin
            return self._token
        return None

    def set(self, token: str, ttl_seconds: float):
        self._token = token
        self._expires_at = time.time() + max(0.0, ttl_seconds)

    def clear(self):
        self._token = None
        self._expires_at = 0.0
