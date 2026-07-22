"""Cohort (анги) scheduling + enrollment.

- Staff (cohort:manage): create/update/delete cohorts, assign teacher+classroom
  (double-booking across overlapping date ranges is blocked).
- Public: browse open cohorts.
- Students self-enroll; staff (enrollment:create) enroll on their behalf.
"""
from datetime import date

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.auth import actor_required, has_permission, require_permission
from app.extensions import db
from app.models import (
    COHORT_STATUSES,
    Classroom,
    Cohort,
    Course,
    Enrollment,
    Student,
    Teacher,
)
from app.routes.common import json_fail

bp = Blueprint("cohorts", __name__)

_WRITABLE = {"course_id", "parent_cohort_id", "name", "teacher_id", "classroom_id",
             "capacity", "status", "schedule_note"}
_DATE_FIELDS = {"start_date", "end_date", "graduation_date"}


# ---------------------------------------------------------------- helpers
def _can_manage() -> bool:
    u = getattr(g, "current_user", None)
    return u is not None and has_permission(u.role, "cohort:manage")


def _apply(cohort, data):
    for key in _WRITABLE:
        if key in data:
            setattr(cohort, key, data[key])
    for key in _DATE_FIELDS:
        if key in data:
            value = data[key]
            if value in (None, ""):
                setattr(cohort, key, None)
                continue
            try:
                setattr(cohort, key, date.fromisoformat(value))
            except (ValueError, TypeError):
                json_fail(400, "invalid_date", field=key)


def _validate(cohort):
    if not cohort.name:
        json_fail(400, "name_required")
    if not cohort.course_id or db.session.get(Course, cohort.course_id) is None:
        json_fail(400, "invalid_course_id")
    if cohort.status not in COHORT_STATUSES:
        json_fail(400, "invalid_status")
    if cohort.teacher_id and db.session.get(Teacher, cohort.teacher_id) is None:
        json_fail(400, "invalid_teacher_id")
    if cohort.classroom_id and db.session.get(Classroom, cohort.classroom_id) is None:
        json_fail(400, "invalid_classroom_id")
    if cohort.start_date and cohort.end_date and cohort.end_date < cohort.start_date:
        json_fail(400, "end_before_start")


def _overlap_query(column, value, cohort):
    """Cohorts sharing teacher/classroom whose date range overlaps this one."""
    q = Cohort.query.filter(column == value)
    if cohort.id:
        q = q.filter(Cohort.id != cohort.id)
    # Only date-bounded cohorts can conflict; overlap = start<=other.end & end>=other.start.
    if cohort.start_date and cohort.end_date:
        q = q.filter(
            Cohort.start_date.isnot(None),
            Cohort.end_date.isnot(None),
            Cohort.start_date <= cohort.end_date,
            Cohort.end_date >= cohort.start_date,
        )
    else:
        return None
    return q.first()


def _check_conflicts(cohort):
    """Block double-booking a teacher or classroom on overlapping date ranges."""
    if cohort.teacher_id:
        clash = _overlap_query(Cohort.teacher_id, cohort.teacher_id, cohort)
        if clash is not None:
            json_fail(409, "teacher_double_booked",
                      conflict={"cohort_id": clash.id, "name": clash.name,
                                "start_date": clash.start_date.isoformat(),
                                "end_date": clash.end_date.isoformat()})
    if cohort.classroom_id:
        clash = _overlap_query(Cohort.classroom_id, cohort.classroom_id, cohort)
        if clash is not None:
            json_fail(409, "classroom_double_booked",
                      conflict={"cohort_id": clash.id, "name": clash.name,
                                "start_date": clash.start_date.isoformat(),
                                "end_date": clash.end_date.isoformat()})


def _get_or_404(cohort_id):
    cohort = db.session.get(Cohort, cohort_id)
    if cohort is None:
        json_fail(404, "not_found")
    return cohort


# ---------------------------------------------------------------- staff: cohort CRUD
@bp.get("/admin/cohorts")
@require_permission("cohort:manage")
def list_cohorts_admin():
    q = Cohort.query
    status = request.args.get("status")
    if status:
        q = q.filter_by(status=status)
    for field, col in (("course_id", Cohort.course_id), ("teacher_id", Cohort.teacher_id),
                       ("classroom_id", Cohort.classroom_id)):
        val = request.args.get(field)
        if val and val.isdigit():
            q = q.filter(col == int(val))
    rows = q.order_by(Cohort.start_date.is_(None), Cohort.start_date.asc(), Cohort.id.desc()).all()
    return jsonify(cohorts=[c.to_dict() for c in rows])


@bp.get("/admin/cohorts/<int:cohort_id>")
@require_permission("cohort:manage")
def get_cohort_admin(cohort_id):
    return jsonify(_get_or_404(cohort_id).to_dict(detail=True))


@bp.post("/admin/cohorts")
@require_permission("cohort:manage")
def create_cohort():
    cohort = Cohort(status="draft")
    _apply(cohort, request.get_json(silent=True) or {})
    _validate(cohort)
    _check_conflicts(cohort)
    db.session.add(cohort)
    db.session.commit()
    return jsonify(cohort.to_dict(detail=True)), 201


@bp.patch("/admin/cohorts/<int:cohort_id>")
@require_permission("cohort:manage")
def update_cohort(cohort_id):
    cohort = _get_or_404(cohort_id)
    _apply(cohort, request.get_json(silent=True) or {})
    _validate(cohort)
    _check_conflicts(cohort)
    db.session.commit()
    return jsonify(cohort.to_dict(detail=True))


@bp.delete("/admin/cohorts/<int:cohort_id>")
@require_permission("cohort:manage")
def delete_cohort(cohort_id):
    cohort = _get_or_404(cohort_id)
    Enrollment.query.filter_by(cohort_id=cohort.id).delete()
    db.session.delete(cohort)
    db.session.commit()
    return jsonify(status="deleted")


# ---------------------------------------------------------------- public browse
@bp.get("/cohorts")
def list_cohorts_public():
    q = Cohort.query.filter(Cohort.status.in_(("open", "closed")))
    course_id = request.args.get("course_id")
    if course_id and course_id.isdigit():
        q = q.filter(Cohort.course_id == int(course_id))
    rows = q.order_by(Cohort.start_date.is_(None), Cohort.start_date.asc()).all()
    return jsonify(cohorts=[c.to_dict() for c in rows])


@bp.get("/cohorts/<int:cohort_id>")
def get_cohort_public(cohort_id):
    cohort = _get_or_404(cohort_id)
    if not cohort.is_public and not _can_manage():
        json_fail(404, "not_found")
    return jsonify(cohort.to_dict(detail=True))


# ---------------------------------------------------------------- enrollment
def _enroll(cohort, student_id, *, require_open, created_via, admin_id=None):
    if db.session.get(Student, student_id) is None:
        json_fail(404, "student_not_found")
    if require_open and cohort.status != "open":
        json_fail(409, "cohort_not_open")
    if cohort.status == "draft":
        json_fail(409, "cohort_not_open")
    existing = Enrollment.query.filter_by(cohort_id=cohort.id, student_id=student_id).first()
    if existing is not None:
        if existing.status == "active":
            json_fail(409, "already_enrolled")
        existing.status = "active"  # re-activate a cancelled enrollment
        db.session.commit()
        return existing
    if cohort.seats_available == 0:
        json_fail(409, "cohort_full")
    enrollment = Enrollment(
        cohort_id=cohort.id, student_id=student_id, status="active",
        course_id=cohort.course_id, created_via=created_via, created_by_admin_id=admin_id,
    )
    db.session.add(enrollment)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        json_fail(409, "already_enrolled")
    return enrollment


@bp.post("/cohorts/<int:cohort_id>/enroll")
@actor_required("student")
def enroll_self(cohort_id):
    cohort = _get_or_404(cohort_id)
    enrollment = _enroll(cohort, g.current_user.actor_id, require_open=True, created_via="web")
    return jsonify(enrollment.to_dict(with_student=False)), 201


@bp.delete("/cohorts/<int:cohort_id>/enroll")
@actor_required("student")
def cancel_self(cohort_id):
    cohort = _get_or_404(cohort_id)
    enrollment = Enrollment.query.filter_by(
        cohort_id=cohort.id, student_id=g.current_user.actor_id, status="active"
    ).first()
    if enrollment is None:
        json_fail(404, "not_enrolled")
    enrollment.status = "cancelled"
    db.session.commit()
    return jsonify(status="cancelled")


@bp.post("/admin/cohorts/<int:cohort_id>/enroll")
@require_permission("enrollment:create")
def enroll_by_staff(cohort_id):
    cohort = _get_or_404(cohort_id)
    data = request.get_json(silent=True) or {}
    student_id = data.get("student_id")
    if not student_id:
        json_fail(400, "student_id_required")
    enrollment = _enroll(cohort, student_id, require_open=False,
                         created_via="admin", admin_id=g.current_user.actor_id)
    return jsonify(enrollment.to_dict()), 201


@bp.get("/admin/cohorts/<int:cohort_id>/students")
@require_permission("cohort:manage")
def list_cohort_students(cohort_id):
    cohort = _get_or_404(cohort_id)
    rows = Enrollment.query.filter_by(cohort_id=cohort.id, status="active").all()
    return jsonify(cohort_id=cohort.id, count=len(rows),
                   students=[e.to_dict() for e in rows])


@bp.delete("/admin/cohorts/<int:cohort_id>/students/<int:student_id>")
@require_permission("cohort:manage")
def remove_cohort_student(cohort_id, student_id):
    enrollment = Enrollment.query.filter_by(cohort_id=cohort_id, student_id=student_id).first()
    if enrollment is None:
        json_fail(404, "not_enrolled")
    enrollment.status = "cancelled"
    db.session.commit()
    return jsonify(status="removed")
