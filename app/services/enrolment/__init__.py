"""Public enrolment funnel: programme list → lead → seat hold → payment → receipt.

Drives the unauthenticated flow the marketing site uses (see the web repo's
``docs/enrolment-api.md``). Two rules shape everything here:

- **No session, so the token is the authority.** Every step after booking is
  addressed by ``payment_token`` — an opaque random handle. Whoever holds it may
  read that checkout's invoice, status and receipt, and nothing else.
- **The server owns the amount.** Clients may send a figure; it is ignored. The
  charge is derived from the cohort/course price and the promotion actually
  found in the database, so a tampered payload cannot change what is charged.

Field names follow the front-end contract rather than our internal vocabulary,
so the routes stay one-liners: their *classroom course* is our ``Course``, their
*schedule* is our ``Cohort``.

The package splits by funnel step; this module re-exports the public API so
callers keep using ``from app.services import enrolment as svc``.
"""
from .booking import apply_coupon, book_seat
from .catalogue import list_programmes
from .checkout import (
    invoice_status,
    qpay_invoice,
    release_expired_holds,
    storepay_invoice,
    storepay_status,
)
from .courses import create_request, get_classroom_course, list_classroom_courses, list_schedules
from .receipt import receipt_status, set_receipt_customer

__all__ = [
    "apply_coupon",
    "book_seat",
    "create_request",
    "get_classroom_course",
    "invoice_status",
    "list_classroom_courses",
    "list_programmes",
    "list_schedules",
    "qpay_invoice",
    "receipt_status",
    "release_expired_holds",
    "set_receipt_customer",
    "storepay_invoice",
    "storepay_status",
]
