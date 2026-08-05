"""Payment gateway provider registry.

Each gateway is a self-contained module (``qpay``, ``storepay``, ``golomt``) that
never imports Flask or the DB. ``get_provider(name)`` builds one on demand from
the running app's config, so the service layer stays gateway-agnostic:

    from app.payments import get_provider
    provider = get_provider("qpay")
    result = provider.create_invoice(req)

Adding a gateway = drop in a new module + one line in ``_PROVIDERS`` + a config
block. No other layer changes.
"""
from __future__ import annotations

from flask import current_app

from .base import (
    InvoiceRequest,
    InvoiceResult,
    PaymentGatewayError,
    PaymentProvider,
    PaymentStatus,
)
from .golomt import GolomtCorporateProvider
from .qpay import QPayProvider
from .sandbox import SandboxProvider
from .storepay import StorePayProvider

# name -> (provider class, config-builder). The builder pulls the provider's
# settings out of Flask config into a plain dict the class understands.
_PROVIDERS = {
    # Settles without money — see app/payments/sandbox.py. Reachable only when
    # PAYMENTS_SANDBOX is on; the service layer decides, not the caller.
    "sandbox": (SandboxProvider, lambda c: {"timeout": c.get("PAYMENT_HTTP_TIMEOUT", 20)}),
    "qpay": (QPayProvider, lambda c: {
        "base_url": c.get("QPAY_BASE_URL"),
        "username": c.get("QPAY_USERNAME"),
        "password": c.get("QPAY_PASSWORD"),
        "invoice_code": c.get("QPAY_INVOICE_CODE"),
        "timeout": c.get("PAYMENT_HTTP_TIMEOUT", 20),
    }),
    "storepay": (StorePayProvider, lambda c: {
        "base_url": c.get("STOREPAY_BASE_URL"),
        "auth_url": c.get("STOREPAY_AUTH_URL"),
        "client_id": c.get("STOREPAY_CLIENT_ID"),
        "client_secret": c.get("STOREPAY_CLIENT_SECRET"),
        "username": c.get("STOREPAY_USERNAME"),
        "password": c.get("STOREPAY_PASSWORD"),
        "store_id": c.get("STOREPAY_STORE_ID"),
        "token_path": c.get("STOREPAY_TOKEN_PATH", "/oauth/token"),
        "loan_path": c.get("STOREPAY_LOAN_PATH", "/merchant/loan"),
        "details_path": c.get("STOREPAY_DETAILS_PATH", "/merchant/loan/details"),
        "timeout": c.get("PAYMENT_HTTP_TIMEOUT", 20),
    }),
    "golomt": (GolomtCorporateProvider, lambda c: {
        "base_url": c.get("GOLOMT_CORP_BASE_URL"),
        "token": c.get("GOLOMT_CORP_TOKEN"),
        "client_id": c.get("GOLOMT_CORP_CLIENT_ID"),
        "client_secret": c.get("GOLOMT_CORP_CLIENT_SECRET"),
        # Multi-account routing (preferred); single account/name is the fallback.
        "accounts": c.get("GOLOMT_CORP_ACCOUNTS"),
        "account": c.get("GOLOMT_CORP_ACCOUNT"),
        "account_name": c.get("GOLOMT_CORP_ACCOUNT_NAME"),
        "token_path": c.get("GOLOMT_CORP_TOKEN_PATH", "/v1/auth/token"),
        "statement_path": c.get("GOLOMT_CORP_STATEMENT_PATH", "/v1/statement"),
        "match_window_days": c.get("GOLOMT_CORP_MATCH_WINDOW_DAYS", 14),
        "timeout": c.get("PAYMENT_HTTP_TIMEOUT", 20),
    }),
}

# The sandbox settles without money, so it is deliberately NOT in the list a
# caller may name. Everything that validates "is this a real provider?" uses
# SUPPORTED_PROVIDERS; only the service layer reaches sandbox, and only when
# PAYMENTS_SANDBOX is on (enforced in get_provider below).
INTERNAL_PROVIDERS = ("sandbox",)
SUPPORTED_PROVIDERS = tuple(n for n in _PROVIDERS if n not in INTERNAL_PROVIDERS)

__all__ = [
    "INTERNAL_PROVIDERS",
    "InvoiceRequest",
    "InvoiceResult",
    "PaymentGatewayError",
    "PaymentProvider",
    "PaymentStatus",
    "SUPPORTED_PROVIDERS",
    "get_provider",
]


def get_provider(name: str) -> PaymentProvider:
    """Instantiate the provider ``name`` from the current app config.

    Refuses the sandbox unless ``PAYMENTS_SANDBOX`` is on. Without this, naming
    it in a request body would settle a real invoice for free — the flag would
    be decorative.
    """
    entry = _PROVIDERS.get(name)
    if entry is None:
        raise PaymentGatewayError(name or "unknown", "unsupported_provider")
    if name in INTERNAL_PROVIDERS and not current_app.config.get("PAYMENTS_SANDBOX"):
        raise PaymentGatewayError(name, "unsupported_provider")
    cls, build_config = entry
    return cls(build_config(current_app.config))
