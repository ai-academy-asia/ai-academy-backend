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

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from flask import current_app

from app.extensions import db
from app.models import (
    Course,
    Enrollment,
    Invoice,
    Payment,
    PaymentInstallment,
    Student,
    StudentLedger,
)
from app.payments import (
    INTERNAL_PROVIDERS,
    SUPPORTED_PROVIDERS,
    InvoiceRequest,
    PaymentGatewayError,
    PaymentStatus,
    get_provider,
)

from .errors import ServiceError, from_integration_error
from .params import get_by_id, parse_limit


# --------------------------------------------------------------------- helpers
def _to_amount(value) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ServiceError(400, "invalid_amount") from None
    if not amount.is_finite():  # NaN / Infinity parse fine and then break arithmetic
        raise ServiceError(400, "invalid_amount")
    if amount <= 0:
        raise ServiceError(400, "amount_must_be_positive")
    return amount.quantize(Decimal("0.01"))


def _gen_reference(provider: str) -> str:
    """Globally-unique merchant reference: AIAA-QP-<12 hex>. This is what we send
    to the gateway and match a Golomt statement credit on."""
    return f"AIAA-{provider[:2].upper()}-{uuid4().hex[:12].upper()}"


def get_invoice(invoice_id) -> Invoice:
    invoice = get_by_id(Invoice, invoice_id)
    if invoice is None:
        raise ServiceError(404, "invoice_not_found")
    return invoice


def get_invoice_by_ref(ref: str) -> Invoice:
    invoice = Invoice.query.filter_by(sender_invoice_no=ref).first()
    if invoice is None:
        raise ServiceError(404, "invoice_not_found")
    return invoice


# --------------------------------------------------------------- create invoice
def create_invoice(
    provider: str,
    *,
    amount,
    callback_base: str,
    description: str = "",
    enrollment_id=None,
    student_id=None,
    installment_id=None,
    customer: dict | None = None,
) -> Invoice:
    """Raise a payment request through ``provider`` and persist it as an Invoice.

    ``callback_base`` is the public origin (e.g. ``https://api.ai-academy.asia``)
    used to build the gateway callback URL.
    """
    # Any provider the registry knows, including the internal sandbox stub —
    # get_provider is what refuses sandbox when PAYMENTS_SANDBOX is off. Routes
    # that take the name from a request body whitelist SUPPORTED_PROVIDERS
    # themselves; validating it twice here is what broke demo mode.
    if provider not in SUPPORTED_PROVIDERS + INTERNAL_PROVIDERS:
        raise ServiceError(400, "unsupported_provider", supported=list(SUPPORTED_PROVIDERS))
    amount = _to_amount(amount)
    customer = customer or {}

    # Resolve/validate the money-domain links and enrich the customer payload.
    enrollment_id, student_id, installment_id = _resolve_links(
        enrollment_id, student_id, installment_id
    )
    if student_id and not customer:
        customer = _customer_from_student(student_id)

    ref = _gen_reference(provider)
    callback_url = f"{callback_base.rstrip('/')}/payments/{provider}/callback?ref={ref}"
    req = InvoiceRequest(
        sender_invoice_no=ref,
        amount=amount,
        currency="MNT",
        description=description or f"AIAA payment {ref}",
        callback_url=callback_url,
        customer=customer,
        # Golomt routes to a receiving account by course; pass the course hints.
        extra=_course_hint(enrollment_id) if provider == "golomt" else {},
    )

    try:
        result = get_provider(provider).create_invoice(req)
    except PaymentGatewayError as exc:
        raise _as_service_error(exc) from exc

    invoice = Invoice(
        provider=provider,
        enrollment_id=enrollment_id,
        student_id=student_id,
        installment_id=installment_id,
        sender_invoice_no=ref,
        amount=amount,
        currency="MNT",
        description=req.description,
        status="pending",
        provider_invoice_id=result.provider_invoice_id,
        qr_text=result.qr_text,
        qr_image=result.qr_image,
        payment_url=result.payment_url,
        urls=result.urls,
        provider_meta=result.raw,
        expires_at=result.expires_at,
    )
    db.session.add(invoice)
    db.session.commit()
    return invoice


def _resolve_links(enrollment_id, student_id, installment_id):
    if installment_id:
        inst = db.session.get(PaymentInstallment, installment_id)
        if inst is None:
            raise ServiceError(404, "installment_not_found")
        # Settling marks this installment paid, so it must be the enrollment's own.
        if enrollment_id and int(enrollment_id) != inst.enrollment_id:
            raise ServiceError(400, "installment_not_in_enrollment")
        enrollment_id = enrollment_id or inst.enrollment_id
        student_id = student_id or inst.student_id
    if enrollment_id:
        enr = db.session.get(Enrollment, enrollment_id)
        if enr is None:
            raise ServiceError(404, "enrollment_not_found")
        student_id = student_id or enr.student_id
    if student_id and db.session.get(Student, student_id) is None:
        raise ServiceError(404, "student_not_found")
    return enrollment_id, student_id, installment_id


def _customer_from_student(student_id) -> dict:
    s = db.session.get(Student, student_id)
    if s is None:
        return {}
    return {
        "name": f"{s.first_name} {s.last_name or ''}".strip(),
        "phone": getattr(s, "phone", None),
        "email": getattr(s, "email", None),
        "register": getattr(s, "register", None),
    }


def _course_hint(enrollment_id) -> dict:
    """Course slug/title for an enrollment — used by Golomt to route the payment
    to the right receiving account. Empty when there's no linked course."""
    if not enrollment_id:
        return {}
    enr = db.session.get(Enrollment, enrollment_id)
    if enr is None or not enr.course_id:
        return {}
    course = db.session.get(Course, enr.course_id)
    if course is None:
        return {}
    return {
        "course_slug": course.slug,
        "course_title": course.title_mn or course.title_en,
    }


# ------------------------------------------------------------------- settlement
def settle(invoice: Invoice, status: PaymentStatus) -> Payment | None:
    """Record a verified settlement. Idempotent on (provider, provider_payment_id).

    Returns the Payment (new or pre-existing) when paid, else None. Marks the
    invoice + linked installment paid and refreshes the student ledger.
    """
    if not status.paid:
        return None

    txn_id = status.provider_payment_id or invoice.sender_invoice_no
    existing = Payment.query.filter_by(
        provider=invoice.provider, provider_payment_id=txn_id
    ).first()
    if existing is not None:
        if _is_short(invoice, existing.amount):
            return None
        _mark_invoice_paid(invoice, existing.paid_at)  # ensure invoice reflects it
        db.session.commit()
        return existing

    received = status.amount if status.amount is not None else invoice.amount
    if _is_short(invoice, received):
        _record_short_payment(invoice, status, txn_id, received)
        return None

    if invoice.status == "cancelled":
        # Retired when the buyer switched gateway, and paid anyway. The money is
        # real and is recorded, but the booking now points at the other invoice.
        current_app.logger.warning(
            "cancelled invoice %s (%s) was paid — link it to its booking by hand",
            invoice.id, invoice.sender_invoice_no,
        )
    payment = Payment(
        invoice_id=invoice.id,
        provider=invoice.provider,
        provider_payment_id=txn_id,
        amount=received,
        currency=invoice.currency,
        status="paid",
        method=status.method,
        paid_at=status.paid_at or datetime.utcnow(),
        raw=status.raw,
    )
    db.session.add(payment)
    _mark_invoice_paid(invoice, payment.paid_at)
    if invoice.installment_id:
        _mark_installment_paid(invoice.installment_id, payment.paid_at)
    db.session.flush()
    if invoice.enrollment_id:
        recompute_ledger(invoice.enrollment_id)
    db.session.commit()
    _issue_ebarimt(payment)
    return payment


def _is_short(invoice: Invoice, received) -> bool:
    return received is not None and Decimal(str(received)) < Decimal(str(invoice.amount))


def _record_short_payment(invoice: Invoice, status: PaymentStatus, txn_id, received):
    """Book money that arrived short of the invoice, without settling anything.

    The money is real, so it is recorded and counts toward the ledger — but the
    invoice stays open and its installment unpaid: marking them paid would clear
    a debt the buyer has not covered. No receipt is issued either; the seat and
    the tax receipt wait for finance, who find these by the log line below.
    """
    payment = Payment(
        invoice_id=invoice.id,
        provider=invoice.provider,
        provider_payment_id=txn_id,
        amount=received,
        currency=invoice.currency,
        status="paid",
        method=status.method,
        paid_at=status.paid_at or datetime.utcnow(),
        raw=status.raw,
    )
    db.session.add(payment)
    db.session.flush()
    if invoice.enrollment_id:
        recompute_ledger(invoice.enrollment_id)
    db.session.commit()
    current_app.logger.warning(
        "underpayment on invoice %s (%s): received %s of %s — left open for finance",
        invoice.id, invoice.sender_invoice_no, received, invoice.amount,
    )


def _issue_ebarimt(payment: Payment):
    """Auto-issue an eBarimt receipt for a fresh settlement (best-effort, temp-aware)."""
    from app.services import ebarimt as ebarimt_svc  # local import avoids import cycle
    ebarimt_svc.issue_if_enabled(payment)


def _mark_invoice_paid(invoice: Invoice, when):
    invoice.status = "paid"
    invoice.paid_at = invoice.paid_at or when or datetime.utcnow()


def _mark_installment_paid(installment_id, when):
    inst = db.session.get(PaymentInstallment, installment_id)
    if inst is not None and inst.status != "paid":
        inst.status = "paid"
        inst.paid_at = when or datetime.utcnow()


# ------------------------------------------------------------------- callbacks
def handle_callback(provider: str, ref: str | None, payload: dict, headers: dict) -> dict:
    """Process an inbound gateway webhook. Always re-verifies with the gateway
    (never trusts the callback body) before settling."""
    if provider not in SUPPORTED_PROVIDERS:
        raise ServiceError(400, "unsupported_provider")
    invoice = _find_invoice_for_callback(provider, ref, payload)
    # Verify with the gateway that actually raised this invoice, not the one
    # named in the URL. Trusting the path would let anyone settle a QPay
    # invoice by posting to another provider's callback with its reference.
    if invoice.provider != provider:
        raise ServiceError(404, "invoice_not_found")
    try:
        status = get_provider(invoice.provider).verify_callback(invoice, payload, headers)
    except PaymentGatewayError as exc:
        raise _as_service_error(exc) from exc
    payment = settle(invoice, status)
    return {
        "ref": invoice.sender_invoice_no,
        "invoice_id": invoice.id,
        "status": invoice.status,
        "paid": bool(payment),
    }


def _find_invoice_for_callback(provider, ref, payload):
    if ref:
        return get_invoice_by_ref(ref)
    # Fall back to provider-specific ids echoed in the body.
    candidates = [
        payload.get("sender_invoice_no"),
        payload.get("orderId"),
        payload.get("reference"),
    ]
    for value in candidates:
        if value:
            inv = Invoice.query.filter_by(sender_invoice_no=value).first()
            if inv:
                return inv
    provider_id = payload.get("invoice_id") or payload.get("loanId") or payload.get("payment_id")
    if provider_id:
        inv = Invoice.query.filter_by(
            provider=provider, provider_invoice_id=str(provider_id)
        ).first()
        if inv:
            return inv
    raise ServiceError(404, "invoice_not_found")


# ------------------------------------------------------------- status / polling
def check_status(invoice: Invoice) -> Invoice:
    """Poll the gateway and settle if newly paid. Safe to call repeatedly."""
    if invoice.status == "paid":
        return invoice
    try:
        status = get_provider(invoice.provider).check_invoice(invoice)
    except PaymentGatewayError as exc:
        raise _as_service_error(exc) from exc
    settle(invoice, status)
    return invoice


# ----------------------------------------------------------- Golomt reconcile
def reconcile_golomt(from_date: date, to_date: date) -> dict:
    """Pull the Golomt corporate statement and settle any pending bank-transfer
    invoices whose reference + amount match a credit. Returns a summary."""
    provider = get_provider("golomt")
    try:
        txns = provider.fetch_all_statements(from_date, to_date)
    except PaymentGatewayError as exc:
        raise _as_service_error(exc) from exc

    pending = Invoice.query.filter_by(provider="golomt", status="pending").all()
    matched, settled = [], 0
    for invoice in pending:
        for txn in txns:
            if provider.matches(invoice, txn):
                status = PaymentStatus(
                    paid=True, provider_payment_id=txn.txn_id or invoice.sender_invoice_no,
                    amount=txn.amount, paid_at=txn.posted_at, method="transfer", raw=txn.raw,
                )
                if settle(invoice, status):
                    settled += 1
                    matched.append({"invoice_id": invoice.id, "ref": invoice.sender_invoice_no,
                                    "txn_id": txn.txn_id, "amount": float(txn.amount),
                                    "account": txn.account})
                break
    return {
        "from": from_date.isoformat(), "to": to_date.isoformat(),
        "statement_txns": len(txns), "pending_invoices": len(pending),
        "settled": settled, "matched": matched,
    }


# ------------------------------------------------------------------- ledger
def recompute_ledger(enrollment_id) -> StudentLedger:
    """Rebuild the enrollment's receivable summary from source rows.

    total_paid  = Σ verified Payments (net of refunds) on this enrollment's invoices
    total_due   = Σ installment amounts if a plan exists, else total_paid
    next_due    = earliest unpaid installment's due date
    """
    enr = db.session.get(Enrollment, enrollment_id)
    if enr is None:
        raise ServiceError(404, "enrollment_not_found")

    paid = db.session.query(db.func.coalesce(db.func.sum(
        Payment.amount - db.func.coalesce(Payment.refunded_amount, 0)
    ), 0)).join(Invoice, Payment.invoice_id == Invoice.id).filter(
        Invoice.enrollment_id == enrollment_id, Payment.status != "refunded"
    ).scalar() or Decimal(0)

    installments = PaymentInstallment.query.filter_by(enrollment_id=enrollment_id).all()
    if installments:
        total_due = sum((i.amount or Decimal(0) for i in installments), Decimal(0))
        unpaid = [i for i in installments if i.status not in ("paid", "waived") and i.due_date]
        next_due = min((i.due_date for i in unpaid), default=None)
    else:
        total_due = Decimal(str(paid))
        next_due = None

    ledger = StudentLedger.query.filter_by(enrollment_id=enrollment_id).first()
    if ledger is None:
        ledger = StudentLedger(student_id=enr.student_id, enrollment_id=enrollment_id)
        db.session.add(ledger)
    ledger.total_paid = Decimal(str(paid))
    ledger.total_due = Decimal(str(total_due))
    ledger.next_due_date = next_due
    ledger.recompute_balance()
    return ledger


def get_ledger(enrollment_id) -> StudentLedger:
    ledger = StudentLedger.query.filter_by(enrollment_id=enrollment_id).first()
    if ledger is None:
        raise ServiceError(404, "ledger_not_found")
    return ledger


# ------------------------------------------------------------------- refunds
def compute_refund_amount(payment: Payment, *, pct_attended=None, amount=None) -> Decimal:
    """How much of ``payment`` has gone back once this refund lands — the running
    total, not the increment — without touching anything.

    Split out of :func:`refund` because the eBarimt side has to know the figure
    *before* the money moves: whether the tax receipt is voided outright or
    voided and re-issued for the remainder depends on what the buyer keeps, and
    the PosAPI call has to run before the database write (see
    :mod:`app.services.refunds`).
    """
    original = payment.amount or Decimal(0)
    already = payment.refunded_amount or Decimal(0)
    # The figure is the running total returned, not an increment: re-sending the
    # same request (a double-click, a retry after a timeout) must not pay out twice.
    if amount is not None:
        total = _to_amount(amount)
        if total > original:
            raise ServiceError(400, "refund_exceeds_payment")
    elif pct_attended is not None:
        total = (original * Decimal("0.5")) if int(pct_attended) < 20 else Decimal(0)
        if total <= 0 and already <= 0:
            raise ServiceError(409, "nothing_to_refund", pct_attended=int(pct_attended))
    else:
        raise ServiceError(400, "refund_basis_required")
    # Money already handed back cannot be taken back by a lower figure.
    if total < already:
        raise ServiceError(400, "refund_below_already_refunded",
                           already_refunded=float(already))
    return total


def refund(
    payment: Payment, *, pct_attended: int | None = None, amount=None, reason=None
) -> Payment:
    """Apply a refund. Pilot rule: attendance <20% → 50% back, ≥20% → nothing.

    ``amount`` overrides the computed refund (finance discretion) and is the
    total returned, including any earlier partial refund. Recomputes the ledger
    afterward.

    Money only — the tax receipt and the seat are the caller's business. Go
    through :mod:`app.services.refunds` unless you mean to touch just this row.
    """
    if payment.status == "refunded":
        raise ServiceError(409, "already_refunded")
    original = payment.amount or Decimal(0)
    total = compute_refund_amount(payment, pct_attended=pct_attended, amount=amount)

    payment.refunded_amount = total
    payment.refund_pct_attended = pct_attended
    payment.refund_reason = (str(reason).strip()[:255] or None) if reason else None
    payment.refunded_at = datetime.utcnow()
    payment.status = "refunded" if total >= original else "partially_refunded"
    db.session.flush()
    if payment.invoice and payment.invoice.enrollment_id:
        recompute_ledger(payment.invoice.enrollment_id)
    db.session.commit()
    return payment


# ------------------------------------------------------------------- listings
def list_invoices(*, provider=None, status=None, enrollment_id=None, student_id=None, limit=50):
    q = Invoice.query
    if provider:
        q = q.filter_by(provider=provider)
    if status:
        q = q.filter_by(status=status)
    if enrollment_id and str(enrollment_id).isdigit():
        q = q.filter_by(enrollment_id=int(enrollment_id))
    if student_id and str(student_id).isdigit():
        q = q.filter_by(student_id=int(student_id))
    return q.order_by(Invoice.id.desc()).limit(parse_limit(limit)).all()


def list_payments(*, provider=None, status=None, invoice_id=None, limit=50):
    q = Payment.query
    if provider:
        q = q.filter_by(provider=provider)
    if status:
        q = q.filter_by(status=status)
    if invoice_id and str(invoice_id).isdigit():
        q = q.filter_by(invoice_id=int(invoice_id))
    return q.order_by(Payment.id.desc()).limit(parse_limit(limit)).all()


def get_payment(payment_id) -> Payment:
    payment = get_by_id(Payment, payment_id)
    if payment is None:
        raise ServiceError(404, "payment_not_found")
    return payment


# --------------------------------------------------------------------- errors
def _as_service_error(exc: PaymentGatewayError) -> ServiceError:
    """Translate a low-level gateway failure into an HTTP-shaped ServiceError.

    Configuration problems are ours, not the gateway's, so they get their own
    statuses; everything else follows the shared retriable -> 503/502 rule.
    """
    if exc.message in ("not_configured", "unsupported_provider"):
        status = 501 if exc.message == "not_configured" else 400
        return ServiceError(
            status, f"gateway_{exc.message}", provider=exc.provider,
            internal=exc.detail,
        )
    return from_integration_error(exc, prefix="gateway_", provider=exc.provider)
