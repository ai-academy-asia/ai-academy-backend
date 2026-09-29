"""Push tokens and in-app notifications.

``/me/...`` works for any authenticated account (student, teacher or staff);
``POST /admin/notifications`` sends an announcement (``cohort:manage``).
"""
from flask import Blueprint, g, jsonify, request

from app.auth import login_required, require_permission
from app.services import notifications as svc

from ._shared import body

bp = Blueprint("notifications", __name__)


@bp.post("/me/push-tokens")
@login_required
def register_push_token():
    payload, created = svc.register_token(g.current_user.id, body())
    return jsonify(payload), 201 if created else 200


@bp.delete("/me/push-tokens")
@login_required
def remove_push_token():
    removed = svc.remove_token(g.current_user.id, body())
    return jsonify(status="deleted", removed=removed)


@bp.get("/me/notifications")
@login_required
def list_notifications():
    return jsonify(svc.list_for(
        g.current_user.id,
        limit=request.args.get("limit"), before_id=request.args.get("before_id"),
    ))


@bp.post("/me/notifications/<int:notification_id>/read")
@login_required
def read_notification(notification_id):
    return jsonify(svc.mark_read(g.current_user.id, notification_id))


@bp.post("/me/notifications/read-all")
@login_required
def read_all_notifications():
    return jsonify(svc.mark_all_read(g.current_user.id))


@bp.post("/admin/notifications")
@require_permission("cohort:manage")
def send_notification():
    return jsonify(svc.send_announcement(body())), 201
