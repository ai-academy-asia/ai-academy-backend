"""Payment orchestration — the one place that ties the gateways to the money domain.

Routes call these functions; providers (``app.payments``) do the gateway I/O; this
layer persists Invoices/Payments, keeps :class:`StudentLedger` in sync, and maps
:class:`PaymentGatewayError` onto the app's HTTP ``ServiceError``.

The three gateways differ in *how* money is confirmed, but settlement is uniform:
    QPay      → callback → payment/check      → settle()
    StorePay  → callback → loan/details       → settle()
    Golomt    → statement reconcile (pull)    → settle()
``settle()`` is idempotent, so replayed callbacks and re-runs of the Golomt
reconcile never double-count.
"""
from __future__ import annotations

from .callbacks import check_status, handle_callback, reconcile_golomt
from .helpers import get_invoice, get_invoice_by_ref
from .invoices import create_invoice
from .ledger import get_ledger, recompute_ledger
from .listings import get_payment, list_invoices, list_payments
from .refund_money import compute_refund_amount, refund
from .settlement import settle

__all__ = [
    "check_status",
    "compute_refund_amount",
    "create_invoice",
    "get_invoice",
    "get_invoice_by_ref",
    "get_ledger",
    "get_payment",
    "handle_callback",
    "list_invoices",
    "list_payments",
    "recompute_ledger",
    "reconcile_golomt",
    "refund",
    "settle",
]
