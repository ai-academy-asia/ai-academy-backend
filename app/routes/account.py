"""The signed-in user's own money, receipts, profile and password reset.

- ``/me/ledger``, ``/me/invoices``, ``/me/receipts[/<id>]`` : student only
- ``PATCH /me/profile``                                    : student or teacher
- ``/auth/forgot-password``, ``/auth/reset-password``       : anonymous
"""
from flask import Blueprint, g, jsonify, request

from app.auth import actor_required, login_required
from app.services import account as account_svc

from ._shared import body

bp = Blueprint("account", __name__)


# ------------------------------------------------------------------- money
@bp.get("/me/ledger")
@actor_required("student")
def my_ledger():
    return jsonify(account_svc.ledger_overview(g.current_user.actor_id))


@bp.get("/me/invoices")
@actor_required("student")
def my_invoices():
    return jsonify(account_svc.list_invoices(
        g.current_user.actor_id, status=request.args.get("status"),
        limit=request.args.get("limit")))


@bp.get("/me/receipts")
@actor_required("student")
def my_receipts():
    return jsonify(account_svc.list_receipts(
        g.current_user.actor_id, limit=request.args.get("limit")))


@bp.get("/me/receipts/<receipt_id>")
@actor_required("student")
def my_receipt(receipt_id):
    return jsonify(account_svc.get_receipt(g.current_user.actor_id, receipt_id))


# ------------------------------------------------------------------- profile
@bp.patch("/me/profile")
@login_required
def update_my_profile():
    return jsonify(account_svc.update_profile(g.current_user, body()))


# ------------------------------------------------------------------- password reset
@bp.post("/auth/forgot-password")
def forgot_password():
    """Always ``ok`` — the answer must not reveal whether the email has an account."""
    account_svc.request_reset(body().get("email"))
    return jsonify(status="ok")


@bp.post("/auth/reset-password")
def reset_password():
    data = body()
    account_svc.reset_password(data.get("email"), data.get("code"), data.get("new_password"))
    return jsonify(status="ok")
