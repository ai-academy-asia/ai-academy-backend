"""Finance's view of an enrollment's installment plan (хуваарьт төлбөр).

A plan is laid out automatically at enrolment from the course rule; these routes
let finance read it, lay out the default for an older enrollment, and add, edit,
remove or waive installments that are still unpaid. Each change rebuilds the
ledger, so ``balance`` and ``next_due_date`` follow at once.
"""
from flask import Blueprint, jsonify

from app.auth import require_permission
from app.services.payments import plans

from ._shared import body

bp = Blueprint("installments", __name__)


@bp.get("/admin/enrollments/<int:enrollment_id>/installments")
@require_permission("ledger:read")
def get_plan(enrollment_id):
    return jsonify(plans.plan(plans.get_enrollment(enrollment_id)))


@bp.post("/admin/enrollments/<int:enrollment_id>/installments")
@require_permission("installment:manage")
def add_installment(enrollment_id):
    inst = plans.add_installment(plans.get_enrollment(enrollment_id), body())
    return jsonify(inst.to_dict()), 201


@bp.post("/admin/enrollments/<int:enrollment_id>/installments/default")
@require_permission("installment:manage")
def create_default_plan(enrollment_id):
    """The course-rule plan for an enrollment made before plans existed."""
    enr = plans.get_enrollment(enrollment_id)
    plans.create_default_plan(enr)
    return jsonify(plans.plan(enr)), 201


@bp.patch("/admin/installments/<int:installment_id>")
@require_permission("installment:manage")
def update_installment(installment_id):
    inst = plans.update_installment(plans.get_installment(installment_id), body())
    return jsonify(inst.to_dict())


@bp.delete("/admin/installments/<int:installment_id>")
@require_permission("installment:manage")
def delete_installment(installment_id):
    plans.delete_installment(plans.get_installment(installment_id))
    return jsonify(status="deleted")


@bp.post("/admin/installments/<int:installment_id>/waive")
@require_permission("installment:manage")
def waive_installment(installment_id):
    return jsonify(plans.waive_installment(plans.get_installment(installment_id)).to_dict())
