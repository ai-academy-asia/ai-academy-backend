"""Admin-facing router: back-office management of students, teachers,
classrooms, cohorts, course content (writes + templates) and schedules.
Each endpoint is permission-gated; the logic lives in app.services."""
import io

from flask import Blueprint, current_app, g, jsonify, request, send_file

from app.auth import require_permission
from app.services import classrooms as classrooms_svc
from app.services import cohorts as cohorts_svc
from app.services import courses as courses_svc
from app.services import enrollments as enroll_svc
from app.services import schedules as sched_svc
from app.services import users as users_svc
from app.services.errors import ServiceError

from ._shared import can_any

bp = Blueprint("admin", __name__)


def _body():
    return request.get_json(silent=True) or {}


# ============================================================ students / teachers
def _register_user_crud(segment):
    cfg = users_svc.ACTORS[segment]
    guard = require_permission(cfg["permission"])

    def list_users():
        return jsonify(users_svc.list_users(
            cfg, search=request.args.get("q"),
            limit=request.args.get("limit", 50), offset=request.args.get("offset", 0),
        ))

    def get_user(profile_id):
        return jsonify(users_svc.get_user(cfg, profile_id))

    def create_user():
        return jsonify(users_svc.create_user(cfg, _body())), 201

    def update_user(profile_id):
        return jsonify(users_svc.update_user(cfg, profile_id, _body()))

    def delete_user(profile_id):
        users_svc.delete_user(cfg, profile_id)
        return jsonify(status="deleted")

    def reset_password(profile_id):
        users_svc.reset_password(
            cfg, profile_id, _body().get("new_password") or "",
            min_len=current_app.config["PASSWORD_MIN_LENGTH"],
        )
        return jsonify(status="ok")

    base = f"/admin/{segment}"
    item = f"{base}/<int:profile_id>"
    for name, rule, methods, view in [
        ("list", base, ["GET"], list_users),
        ("create", base, ["POST"], create_user),
        ("get", item, ["GET"], get_user),
        ("update", item, ["PATCH"], update_user),
        ("delete", item, ["DELETE"], delete_user),
        ("reset_password", f"{item}/reset-password", ["POST"], reset_password),
    ]:
        bp.add_url_rule(rule, endpoint=f"{segment}_{name}",
                        view_func=guard(view), methods=methods)


for _segment in users_svc.ACTORS:
    _register_user_crud(_segment)


# ============================================================ classrooms (super_admin)
@bp.get("/admin/classrooms")
@require_permission("classroom:manage")
def list_classrooms():
    rows = classrooms_svc.list_classrooms(
        search=request.args.get("q"), active=request.args.get("active"))
    return jsonify(classrooms=[c.to_dict() for c in rows])


@bp.get("/admin/classrooms/<int:classroom_id>")
@require_permission("classroom:manage")
def get_classroom(classroom_id):
    return jsonify(classrooms_svc.get_or_404(classroom_id).to_dict())


@bp.post("/admin/classrooms")
@require_permission("classroom:manage")
def create_classroom():
    return jsonify(classrooms_svc.create_classroom(_body()).to_dict()), 201


@bp.patch("/admin/classrooms/<int:classroom_id>")
@require_permission("classroom:manage")
def update_classroom(classroom_id):
    classroom = classrooms_svc.get_or_404(classroom_id)
    return jsonify(classrooms_svc.update_classroom(classroom, _body()).to_dict())


@bp.delete("/admin/classrooms/<int:classroom_id>")
@require_permission("classroom:manage")
def delete_classroom(classroom_id):
    classrooms_svc.delete_classroom(classrooms_svc.get_or_404(classroom_id))
    return jsonify(status="deleted")


# ============================================================ cohorts (cohort:manage)
@bp.get("/admin/cohorts")
@require_permission("cohort:manage")
def list_cohorts():
    rows = cohorts_svc.list_admin(
        status=request.args.get("status"), course_id=request.args.get("course_id"),
        teacher_id=request.args.get("teacher_id"), classroom_id=request.args.get("classroom_id"))
    return jsonify(cohorts=[c.to_dict() for c in rows])


@bp.get("/admin/cohorts/<int:cohort_id>")
@require_permission("cohort:manage")
def get_cohort(cohort_id):
    return jsonify(cohorts_svc.get_or_404(cohort_id).to_dict(detail=True))


@bp.post("/admin/cohorts")
@require_permission("cohort:manage")
def create_cohort():
    return jsonify(cohorts_svc.create_cohort(_body()).to_dict(detail=True)), 201


@bp.patch("/admin/cohorts/<int:cohort_id>")
@require_permission("cohort:manage")
def update_cohort(cohort_id):
    cohort = cohorts_svc.get_or_404(cohort_id)
    return jsonify(cohorts_svc.update_cohort(cohort, _body()).to_dict(detail=True))


@bp.delete("/admin/cohorts/<int:cohort_id>")
@require_permission("cohort:manage")
def delete_cohort(cohort_id):
    cohorts_svc.delete_cohort(cohorts_svc.get_or_404(cohort_id))
    return jsonify(status="deleted")


@bp.post("/admin/cohorts/<int:cohort_id>/enroll")
@require_permission("enrollment:create")
def enroll_by_staff(cohort_id):
    cohort = cohorts_svc.get_or_404(cohort_id)
    student_id = _body().get("student_id")
    if not student_id:
        raise ServiceError(400, "student_id_required")
    enrollment = enroll_svc.enroll(
        cohort, student_id, require_open=False,
        created_via="admin", admin_id=g.current_user.actor_id)
    return jsonify(enrollment.to_dict()), 201


@bp.get("/admin/cohorts/<int:cohort_id>/students")
@require_permission("cohort:manage")
def list_cohort_students(cohort_id):
    cohort = cohorts_svc.get_or_404(cohort_id)
    rows = enroll_svc.roster(cohort)
    return jsonify(cohort_id=cohort.id, count=len(rows), students=[e.to_dict() for e in rows])


@bp.delete("/admin/cohorts/<int:cohort_id>/students/<int:student_id>")
@require_permission("cohort:manage")
def remove_cohort_student(cohort_id, student_id):
    enroll_svc.remove(cohort_id, student_id)
    return jsonify(status="removed")


# ============================================================ course content (course:edit)
@bp.post("/courses")
@require_permission("course:edit")
def create_course():
    return jsonify(courses_svc.create_course(_body()).to_detail()), 201


@bp.patch("/courses/<id_or_slug>")
@require_permission("course:edit")
def update_course(id_or_slug):
    course = courses_svc.get_course(id_or_slug)
    return jsonify(courses_svc.update_course(course, _body()).to_detail())


@bp.delete("/courses/<id_or_slug>")
@require_permission("course:edit")
def delete_course(id_or_slug):
    courses_svc.delete_course(courses_svc.get_course(id_or_slug))
    return jsonify(status="deleted")


@bp.put("/courses/<id_or_slug>/templates/<kind>")
@require_permission("course:edit")
def upload_template(id_or_slug, kind):
    course = courses_svc.get_course(id_or_slug)
    filename = courses_svc.upload_template(
        course, kind, request.files.get("file"),
        content_length=request.content_length,
        max_bytes=current_app.config["MAX_TEMPLATE_BYTES"])
    return jsonify(status="ok", kind=kind, filename=filename)


@bp.get("/courses/<id_or_slug>/templates/<kind>")
@require_permission("course:edit")
def download_template(id_or_slug, kind):
    course = courses_svc.get_course(id_or_slug)
    data, mimetype, name = courses_svc.read_template(course, kind)
    return send_file(io.BytesIO(data), mimetype=mimetype,
                     as_attachment=True, download_name=name)


@bp.delete("/courses/<id_or_slug>/templates/<kind>")
@require_permission("course:edit")
def delete_template(id_or_slug, kind):
    course = courses_svc.get_course(id_or_slug)
    courses_svc.delete_template(course, kind)
    return jsonify(status="deleted")


# ============================================================ schedules
@bp.get("/admin/schedule/teachers")
@require_permission("schedule:manage")
def all_teacher_schedules():
    from_date, to_date = sched_svc.parse_range(
        request.args.get("from"), request.args.get("to"))
    teachers = sched_svc.overview_teachers(
        from_date, to_date, only_available=request.args.get("available") == "true")
    return jsonify(**sched_svc.range_meta(from_date, to_date),
                   count=len(teachers), teachers=teachers)


@bp.get("/admin/schedule/classrooms")
@require_permission("schedule:manage")
def all_classroom_schedules():
    from_date, to_date = sched_svc.parse_range(
        request.args.get("from"), request.args.get("to"))
    classrooms = sched_svc.overview_classrooms(
        from_date, to_date, only_available=request.args.get("available") == "true")
    return jsonify(**sched_svc.range_meta(from_date, to_date),
                   count=len(classrooms), classrooms=classrooms)


@bp.get("/classrooms/<int:classroom_id>/schedule")
def classroom_schedule(classroom_id):
    if not can_any("cohort:manage", "classroom:manage"):
        raise ServiceError(403 if g.get("current_user") else 401,
                           "forbidden" if g.get("current_user") else "authentication_required")
    return jsonify(classroom_id=classroom_id,
                   cohorts=sched_svc.classroom_schedule(classroom_id))
