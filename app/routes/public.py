"""Public router — the anonymous visitor.

The fourth actor alongside student / teacher / admin, and the only one without
credentials: the marketing site has no accounts, so nothing here carries an
Authorization header and no route may assume ``g.current_user``.

Paths and payload keys are the front-end contract verbatim (the web repo's
``docs/enrolment-api.md``) so the client needs no translation layer. Everything
after step 3 is addressed by ``payment_token``; the routes stay one-liners and
``app.services.enrolment`` owns the rules.

Because these endpoints are open, they are the ones that need rate limiting at
the edge (nginx) — a note, not something this layer enforces.
"""
from flask import Blueprint, jsonify, request

from app.services import enrolment as svc
from app.services.errors import ServiceError

from ._shared import body

bp = Blueprint("public", __name__)


# 0 — the programme catalogue
@bp.get("/programmes")
def list_programmes():
    return jsonify(svc.list_programmes(locale=request.args.get("locale", "mn")))


# 1 — register the enquiry
@bp.post("/classroom-requests")
def create_classroom_request():
    return jsonify(svc.create_request(body()).to_dict()), 201


# 7 — promo code (optional; 404 = "код олдсонгүй")
@bp.post("/classroom-requests/<int:request_id>/coupon")
def apply_coupon(request_id):
    return jsonify(svc.apply_coupon(request_id, body()).to_dict())


# programme pages (the front-end's classroom.listCourses / getCourse)
@bp.get("/classroom-courses")
def list_classroom_courses():
    return jsonify(svc.list_classroom_courses())


@bp.get("/classroom-courses/<int:course_id>")
def get_classroom_course(course_id):
    return jsonify(svc.get_classroom_course(course_id))


# 2 — read the seats
@bp.get("/classroom-courses/<int:course_id>/schedules")
def list_schedules(course_id):
    return jsonify(svc.list_schedules(course_id))


# 3 — hold the seat
@bp.post("/classroom-courses/<int:course_id>/bookings")
def book_seat(course_id):
    return jsonify(svc.book_seat(course_id, body()).to_dict()), 201


# 4 — create the QPay invoice
@bp.get("/payments/qpay/invoice")
def qpay_invoice():
    return jsonify(svc.qpay_invoice(request.args.get("pt", "")))


# 5 — check payment
@bp.get("/payments/invoice/status")
def invoice_status():
    return jsonify(svc.invoice_status(request.args.get("pt", "")))


# 6 — the и-баримт
@bp.get("/payments/receipt")
def receipt_status():
    return jsonify(svc.receipt_status(request.args.get("pt", "")))


@bp.post("/payments/receipt")
def set_receipt_customer():
    """Say who the и-баримт is for, then issue and email it.

    ``{"customer_type": "individual"}`` or
    ``{"customer_type": "organization", "customer_register": "<ТТД>"}``.
    """
    return jsonify(svc.set_receipt_customer(request.args.get("pt", ""), body()))


@bp.get("/payments/taxpayer")
def find_taxpayer():
    """Confirm a company name from its TIN before filing a receipt against it."""
    from app.services import ebarimt as ebarimt_svc

    found = ebarimt_svc.find_taxpayer(request.args.get("tin", ""))
    if found is None:
        raise ServiceError(404, "organization_not_found")
    return jsonify(found)


# 8 — StorePay (optional)
@bp.post("/payments/storepay/invoice")
def storepay_invoice():
    return jsonify(svc.storepay_invoice(body())), 201


@bp.get("/payments/storepay/invoice/<request_id>")
def storepay_status(request_id):
    """``request_id`` is the payment token handed back by the invoice call."""
    return jsonify(svc.storepay_status(request_id))
