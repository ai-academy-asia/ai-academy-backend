"""eBarimt router — finance's back-office for tax receipts (``/admin/ebarimt/*``).

List / inspect / issue / (re)email receipts, flush them to the tax authority,
render the QR, replay temp receipts once PosAPI is live, and void one by hand.
All gated on ``ebarimt:manage``. Split out of the payments router.
"""
import io

import segno
from flask import Blueprint, Response, jsonify, request

from app.auth import require_permission
from app.services import ebarimt as ebarimt_svc
from app.services import payments as pay_svc
from app.services.errors import ServiceError
from app.services.params import parse_limit

from ._shared import body

bp = Blueprint("ebarimt", __name__)


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
    limit = parse_limit(body().get("limit"), default=200, maximum=1000)
    return jsonify(ebarimt_svc.reissue_all_temp(limit=limit))


@bp.post("/admin/ebarimt/<int:receipt_id>/return")
@require_permission("ebarimt:manage")
def return_receipt(receipt_id):
    return jsonify(ebarimt_svc.return_receipt(ebarimt_svc.get_receipt(receipt_id)).to_dict())
