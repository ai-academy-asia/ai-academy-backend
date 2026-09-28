"""Payments router — one blueprint for all three gateways.

Three audiences share it:
- **public**  : gateway callbacks (``/payments/<provider>/callback``) — no auth,
  re-verified server-side before settling.
- **student** : create an invoice to pay for their own enrollment + poll status.
- **finance** : list payments/invoices, refund, run the Golomt reconcile, read ledger.
"""
from datetime import date, timedelta

from flask import Blueprint, current_app, g, jsonify, request

from app.auth import actor_required, require_permission
from app.extensions import db
from app.models import Enrollment, PaymentInstallment
from app.payments import SUPPORTED_PROVIDERS
from app.services import payments as pay_svc
from app.services import refunds as refund_svc
from app.services.errors import ServiceError

from ._shared import body

bp = Blueprint("payments", __name__)


def _callback_base() -> str:
    """Public origin for gateway callbacks — configured host, else the request's."""
    return current_app.config.get("PUBLIC_BASE_URL") or request.url_root.rstrip("/")


# =============================================================== gateway callbacks
@bp.route("/payments/<provider>/callback", methods=["GET", "POST"])
def gateway_callback(provider):
    """Inbound webhook. QPay calls it with query params (GET); StorePay POSTs JSON.
    Always 200s on a known invoice so the gateway stops retrying; settlement is
    re-verified against the gateway inside the service."""
    if provider not in SUPPORTED_PROVIDERS:
        raise ServiceError(404, "unsupported_provider")
    payload = {**request.args.to_dict(), **(request.get_json(silent=True) or {}),
               **request.form.to_dict()}
    ref = request.args.get("ref") or payload.get("ref")
    result = pay_svc.handle_callback(provider, ref, payload, dict(request.headers))
    return jsonify(result)


# =============================================================== student self-pay
@bp.post("/payments/invoices")
@actor_required("student")
def create_my_invoice():
    data = body()
    provider = data.get("provider")
    # Validate the client-named provider here rather than in the service: the
    # service is also called internally with the sandbox stub, which is not a
    # name anyone may pass in.
    if provider not in SUPPORTED_PROVIDERS:
        raise ServiceError(400, "unsupported_provider", supported=list(SUPPORTED_PROVIDERS))
    enrollment_id = data.get("enrollment_id")
    installment_id = data.get("installment_id")

    # A student may only pay for their own enrollment — named directly, or
    # implied by the installment (which carries its enrollment with it).
    if enrollment_id is not None:
        enr = Enrollment.query.filter_by(
            id=enrollment_id, student_id=g.current_user.actor_id
        ).first()
        if enr is None:
            raise ServiceError(403, "not_your_enrollment")
    if installment_id is not None:
        # An unknown installment falls through to the service's 404.
        inst = PaymentInstallment.query.filter_by(id=installment_id).first()
        enr = db.session.get(Enrollment, inst.enrollment_id) if inst is not None else None
        if inst is not None and (enr is None or enr.student_id != g.current_user.actor_id):
            raise ServiceError(403, "not_your_enrollment")

    invoice = pay_svc.create_invoice(
        provider,
        amount=data.get("amount"),
        callback_base=_callback_base(),
        description=data.get("description", ""),
        enrollment_id=enrollment_id,
        student_id=g.current_user.actor_id,
        installment_id=installment_id,
    )
    return jsonify(invoice.to_dict()), 201


@bp.get("/payments/invoices/<int:invoice_id>")
@actor_required("student")
def get_my_invoice(invoice_id):
    invoice = pay_svc.get_invoice(invoice_id)
    if invoice.student_id != g.current_user.actor_id:
        raise ServiceError(403, "forbidden")
    return jsonify(invoice.to_dict())


@bp.get("/payments/invoices/<int:invoice_id>/status")
@actor_required("student")
def poll_my_invoice(invoice_id):
    invoice = pay_svc.get_invoice(invoice_id)
    if invoice.student_id != g.current_user.actor_id:
        raise ServiceError(403, "forbidden")
    invoice = pay_svc.check_status(invoice)
    return jsonify(status=invoice.status, paid=invoice.status == "paid",
                   invoice=invoice.to_dict(with_qr=False))


# =============================================================== finance / admin
@bp.post("/admin/invoices")
@require_permission("payment:read")
def staff_create_invoice():
    data = body()
    invoice = pay_svc.create_invoice(
        data.get("provider"),
        amount=data.get("amount"),
        callback_base=_callback_base(),
        description=data.get("description", ""),
        enrollment_id=data.get("enrollment_id"),
        student_id=data.get("student_id"),
        installment_id=data.get("installment_id"),
        customer=data.get("customer"),
    )
    return jsonify(invoice.to_dict()), 201


@bp.get("/admin/invoices")
@require_permission("payment:read")
def list_invoices():
    rows = pay_svc.list_invoices(
        provider=request.args.get("provider"), status=request.args.get("status"),
        enrollment_id=request.args.get("enrollment_id"),
        student_id=request.args.get("student_id"),
        limit=request.args.get("limit", 50))
    return jsonify(count=len(rows), invoices=[i.to_dict(with_qr=False) for i in rows])


@bp.get("/admin/invoices/<int:invoice_id>")
@require_permission("payment:read")
def get_invoice(invoice_id):
    return jsonify(pay_svc.get_invoice(invoice_id).to_dict())


@bp.post("/admin/invoices/<int:invoice_id>/check")
@require_permission("payment:read")
def check_invoice(invoice_id):
    invoice = pay_svc.check_status(pay_svc.get_invoice(invoice_id))
    return jsonify(status=invoice.status, invoice=invoice.to_dict(with_qr=False))


@bp.get("/admin/payments")
@require_permission("payment:read")
def list_payments():
    rows = pay_svc.list_payments(
        provider=request.args.get("provider"), status=request.args.get("status"),
        invoice_id=request.args.get("invoice_id"), limit=request.args.get("limit", 50))
    return jsonify(count=len(rows), payments=[p.to_dict() for p in rows])


@bp.get("/admin/refunds/lookup")
@require_permission("payment:refund")
def lookup_refund():
    """Resolve one typed-in number to the sale behind it, changing nothing.

    ``?ref=`` takes whatever finance is holding — a lottery number, a ДДТД, a
    payment token — and the server works out which it is. An explicit key
    (``?lottery=``, ``?payment_id=``…) overrides that guess.
    """
    data = {k: v for k, v in request.args.items() if k in refund_svc.REFERENCE_KEYS and v}
    return jsonify(refund_svc.lookup(data or refund_svc.detect_reference(request.args.get("ref"))))


@bp.post("/admin/refunds")
@require_permission("payment:refund")
def create_refund():
    """Refund a payment: void its eBarimt receipt, return the money, free the seat.

    Point at the payment however finance holds it — ``payment_id``,
    ``payment_token``, ``invoice_id``, ``receipt_id``, ``ebarimt_id`` (ДДТД) or
    ``lottery`` ("HQ 92232007"). Amount is ``amount`` or ``pct_attended``.
    """
    data = body()
    if not any(data.get(k) for k in refund_svc.REFERENCE_KEYS):
        data = {**data, **refund_svc.detect_reference(data.get("ref"))}
    return jsonify(refund_svc.refund(data))


@bp.post("/admin/payments/<int:payment_id>/refund")
@require_permission("payment:refund")
def refund_payment(payment_id):
    """Same refund, addressed by payment id. Kept for callers that already hold
    one; the body is identical minus the reference."""
    return jsonify(refund_svc.refund({**body(), "payment_id": payment_id}))


@bp.post("/admin/payments/reconcile/golomt")
@require_permission("payment:read")
def reconcile_golomt():
    data = body()
    to_date = _parse_date(data.get("to")) or date.today()
    from_date = _parse_date(data.get("from")) or (to_date - timedelta(days=14))
    return jsonify(pay_svc.reconcile_golomt(from_date, to_date))


@bp.get("/admin/ledger/<int:enrollment_id>")
@require_permission("ledger:read")
def get_ledger(enrollment_id):
    return jsonify(pay_svc.get_ledger(enrollment_id).to_dict())


@bp.post("/admin/ledger/<int:enrollment_id>/recompute")
@require_permission("ledger:read")
def recompute_ledger(enrollment_id):
    ledger = pay_svc.recompute_ledger(enrollment_id)
    db.session.commit()
    return jsonify(ledger.to_dict())


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ServiceError(400, "invalid_date") from None
