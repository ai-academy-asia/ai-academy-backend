"""Payments router — one blueprint for all three gateways.

Three audiences share it:
- **public**  : gateway callbacks (``/payments/<provider>/callback``) — no auth,
  re-verified server-side before settling.
- **student** : create an invoice to pay for their own enrollment + poll status.
- **finance** : list payments/invoices, refund, run the Golomt reconcile, read ledger.
"""
import io
from datetime import date, timedelta

import segno
from flask import Blueprint, Response, current_app, g, jsonify, request

from app.auth import actor_required, require_permission
from app.models import Enrollment
from app.payments import SUPPORTED_PROVIDERS
from app.services import ebarimt as ebarimt_svc
from app.services import payments as pay_svc
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

    # A student may only pay for their own enrollment.
    if enrollment_id is not None:
        enr = Enrollment.query.filter_by(
            id=enrollment_id, student_id=g.current_user.actor_id
        ).first()
        if enr is None:
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


@bp.post("/admin/payments/<int:payment_id>/refund")
@require_permission("payment:refund")
def refund_payment(payment_id):
    data = body()
    payment = pay_svc.refund(
        pay_svc.get_payment(payment_id),
        pct_attended=data.get("pct_attended"), amount=data.get("amount"))
    return jsonify(payment.to_dict())


@bp.post("/admin/payments/reconcile/golomt")
@require_permission("payment:read")
def reconcile_golomt():
    data = body()
    to_date = _parse_date(data.get("to")) or date.today()
    from_date = _parse_date(data.get("from")) or (to_date - timedelta(days=14))
    return jsonify(pay_svc.reconcile_golomt(from_date, to_date))


# =============================================================== eBarimt receipts
@bp.get("/admin/ebarimt")
@require_permission("ebarimt:manage")
def list_receipts():
    rows = ebarimt_svc.list_receipts(
        status=request.args.get("status"), temp=request.args.get("temp"),
        payment_id=request.args.get("payment_id"), limit=request.args.get("limit", 50))
    return jsonify(count=len(rows), receipts=[r.to_dict() for r in rows])


@bp.get("/admin/ebarimt/summary")
@require_permission("ebarimt:manage")
def ebarimt_summary():
    return jsonify(ebarimt_svc.status_summary())


@bp.get("/admin/ebarimt/<int:receipt_id>")
@require_permission("ebarimt:manage")
def get_receipt(receipt_id):
    return jsonify(ebarimt_svc.get_receipt(receipt_id).to_dict())


@bp.post("/admin/ebarimt/issue")
@require_permission("ebarimt:manage")
def issue_receipt():
    data = body()
    payment_id = data.get("payment_id")
    if not payment_id:
        raise ServiceError(400, "payment_id_required")
    payment = pay_svc.get_payment(payment_id)
    receipt = ebarimt_svc.issue_for_payment(
        payment, type_=data.get("type", "B2C_RECEIPT"),
        customer_register=data.get("customer_register"), description=data.get("description"))
    return jsonify(receipt.to_dict()), 201


@bp.post("/admin/ebarimt/<int:receipt_id>/email")
@require_permission("ebarimt:manage")
def email_receipt(receipt_id):
    """(Re)send the receipt email.

    Issuing already emails the student automatically; this covers the cases that
    need a human — a bounced address, a student asking for it again, or sending
    a copy somewhere else via ``{"to": "..."}``.
    """
    receipt = ebarimt_svc.get_receipt(receipt_id)
    return jsonify(ebarimt_svc.email_receipt(receipt, to=body().get("to")))


@bp.post("/admin/ebarimt/send-data")
@require_permission("ebarimt:manage")
def ebarimt_send_data():
    """Flush issued receipts to the tax authority now, out of schedule.

    The ``ebarimt-sender`` container already does this hourly; this is the manual
    lever for "push it before the report deadline" and for verifying reachability
    after a network change.
    """
    return jsonify(ebarimt_svc.flush_to_tax_authority())


@bp.get("/admin/ebarimt/<int:receipt_id>/qr")
@require_permission("ebarimt:manage")
def receipt_qr(receipt_id):
    """Render the receipt's ``qrData`` as a scannable image.

    ``to_dict()`` already returns the raw ``qr_data`` string, but it is a ~170-char
    blob that no one can verify by eye — this renders it so it can be scanned
    straight out of Postman / the browser. ``?format=svg`` for vector, ``?scale=``
    to size the PNG. 404s while the receipt is still a temp one (no QR yet).
    """
    receipt = ebarimt_svc.get_receipt(receipt_id)
    if not receipt.qr_data:
        raise ServiceError(404, "receipt_has_no_qr")

    fmt = (request.args.get("format") or "png").lower()
    if fmt not in ("png", "svg"):
        raise ServiceError(400, "invalid_format")
    try:
        scale = max(1, min(int(request.args.get("scale", 6)), 20))
    except (TypeError, ValueError):
        raise ServiceError(400, "invalid_scale") from None

    buf = io.BytesIO()
    segno.make(receipt.qr_data, error="m").save(buf, kind=fmt, scale=scale, border=2)
    return Response(
        buf.getvalue(),
        mimetype="image/svg+xml" if fmt == "svg" else "image/png",
        headers={
            "Content-Disposition":
                f'inline; filename="ebarimt-{receipt.ebarimt_id or receipt.id}.{fmt}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@bp.post("/admin/ebarimt/<int:receipt_id>/reissue")
@require_permission("ebarimt:manage")
def reissue_receipt(receipt_id):
    return jsonify(ebarimt_svc.reissue(ebarimt_svc.get_receipt(receipt_id)).to_dict())


@bp.post("/admin/ebarimt/reissue-all")
@require_permission("ebarimt:manage")
def reissue_all_receipts():
    return jsonify(ebarimt_svc.reissue_all_temp(limit=int(body().get("limit", 200))))


@bp.post("/admin/ebarimt/<int:receipt_id>/return")
@require_permission("ebarimt:manage")
def return_receipt(receipt_id):
    return jsonify(ebarimt_svc.return_receipt(ebarimt_svc.get_receipt(receipt_id)).to_dict())


@bp.get("/admin/ledger/<int:enrollment_id>")
@require_permission("ledger:read")
def get_ledger(enrollment_id):
    return jsonify(pay_svc.get_ledger(enrollment_id).to_dict())


@bp.post("/admin/ledger/<int:enrollment_id>/recompute")
@require_permission("ledger:read")
def recompute_ledger(enrollment_id):
    ledger = pay_svc.recompute_ledger(enrollment_id)
    from app.extensions import db
    db.session.commit()
    return jsonify(ledger.to_dict())


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ServiceError(400, "invalid_date") from None
