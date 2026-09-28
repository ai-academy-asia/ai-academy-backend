"""Cohort CRUD, double-booking guard, staff enrollment and roster (/admin/cohorts)."""
from datetime import date

import pytest

from app.models import Cohort, Enrollment


def _fresh(db, model, pk):
    db.session.expire_all()
    return db.session.get(model, pk)


@pytest.fixture
def sales(make_staff):
    return make_staff("sales_enrollment")


@pytest.fixture
def payload(make_course):
    course_id = make_course().id

    def _payload(**fields):
        data = {"course_id": course_id, "name": "Corporate Leaders 2026-10",
                "start_date": "2026-10-01", "end_date": "2026-12-01"}
        data.update(fields)
        return data

    return _payload


def _enroll(client, headers, cohort_id, student_id):
    return client.post(f"/admin/cohorts/{cohort_id}/enroll", headers=headers,
                       json={"student_id": student_id})


# ---------------------------------------------------------------- auth
@pytest.mark.parametrize("method,path", [
    ("get", "/admin/cohorts"), ("post", "/admin/cohorts"), ("get", "/admin/cohorts/1"),
    ("patch", "/admin/cohorts/1"), ("delete", "/admin/cohorts/1"),
    ("post", "/admin/cohorts/1/enroll"), ("get", "/admin/cohorts/1/students"),
    ("delete", "/admin/cohorts/1/students/1"),
])
def test_requires_token(client, method, path):
    resp = getattr(client, method)(path, json={})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


@pytest.mark.parametrize("role", ["finance", "content_marketing"])
def test_forbidden_without_cohort_permissions(client, make_staff, make_cohort, make_student,
                                              role):
    cohort = make_cohort()
    student, _ = make_student()
    _, headers = make_staff(role)
    for method, path in [
        ("get", "/admin/cohorts"), ("post", "/admin/cohorts"),
        ("get", f"/admin/cohorts/{cohort.id}"), ("patch", f"/admin/cohorts/{cohort.id}"),
        ("delete", f"/admin/cohorts/{cohort.id}"),
        ("post", f"/admin/cohorts/{cohort.id}/enroll"),
        ("get", f"/admin/cohorts/{cohort.id}/students"),
        ("delete", f"/admin/cohorts/{cohort.id}/students/{student.actor_id}"),
    ]:
        resp = getattr(client, method)(path, json={"student_id": student.actor_id},
                                       headers=headers)
        assert resp.status_code == 403, (method, path)
        assert resp.get_json()["error"] == "forbidden"
    assert Enrollment.query.count() == 0


def test_students_and_teachers_are_forbidden(client, make_student, make_teacher):
    for _, headers in (make_student(), make_teacher()):
        assert client.get("/admin/cohorts", headers=headers).status_code == 403


# ---------------------------------------------------------------- list / get
def test_list_orders_by_start_date_undated_last(client, sales, make_cohort):
    _, headers = sales
    undated = make_cohort(start_date=None, end_date=None)
    later = make_cohort(start_date=date(2027, 1, 1), end_date=date(2027, 2, 1))
    sooner = make_cohort(start_date=date(2026, 9, 1), end_date=date(2026, 10, 1))
    body = client.get("/admin/cohorts", headers=headers).get_json()
    assert [c["id"] for c in body["cohorts"]] == [sooner.id, later.id, undated.id]


def test_list_filters(client, admin_headers, make_cohort, make_course, make_teacher,
                      make_classroom):
    course = make_course()
    teacher, _ = make_teacher()
    room = make_classroom()
    target = make_cohort(course=course, status="draft", teacher_id=teacher.actor_id,
                         classroom_id=room.id)
    make_cohort(status="open")

    def ids(query):
        body = client.get(f"/admin/cohorts?{query}", headers=admin_headers).get_json()
        return [c["id"] for c in body["cohorts"]]

    assert ids("status=draft") == [target.id]
    assert ids(f"course_id={course.id}") == [target.id]
    assert ids(f"teacher_id={teacher.actor_id}") == [target.id]
    assert ids(f"classroom_id={room.id}") == [target.id]
    assert len(ids("course_id=abc")) == 2  # non-numeric filters are ignored


def test_get_returns_detail(client, admin_headers, make_cohort, make_teacher, make_classroom):
    teacher, _ = make_teacher(first_name="Dorj", last_name="Bat")
    room = make_classroom(name="Lab", center_name="Central")
    cohort = make_cohort(teacher_id=teacher.actor_id, classroom_id=room.id, capacity=5)
    resp = client.get(f"/admin/cohorts/{cohort.id}", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == cohort.id
    assert body["teacher"] == {"id": teacher.actor_id, "name": "Dorj Bat"}
    assert body["classroom"]["name"] == "Lab"
    assert body["course"]["id"] == cohort.course_id
    assert body["seats_available"] == 5
    assert "created_at" in body and "updated_at" in body


def test_get_unknown_is_404(client, admin_headers):
    resp = client.get("/admin/cohorts/9999", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------- create
def test_create_defaults_to_draft(client, sales, payload, make_teacher, make_classroom, db):
    _, headers = sales
    teacher, _ = make_teacher()
    room = make_classroom()
    resp = client.post("/admin/cohorts", headers=headers, json=payload(
        teacher_id=teacher.actor_id, classroom_id=room.id, capacity=12,
        meeting_days=["mon", "wed"], start_time="18:00", end_time="20:00",
        graduation_date="2026-12-05", schedule_note="Evening",
    ))
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "draft"
    assert body["meeting_days"] == ["mon", "wed"]
    assert body["graduation_date"] == "2026-12-05"
    assert body["teacher"]["id"] == teacher.actor_id
    cohort = db.session.get(Cohort, body["id"])
    assert cohort.classroom_id == room.id
    assert cohort.start_date == date(2026, 10, 1)
    assert cohort.capacity == 12


@pytest.mark.parametrize("fields,error", [
    ({"name": ""}, "name_required"),
    ({"course_id": None}, "invalid_course_id"),
    ({"course_id": 9999}, "invalid_course_id"),
    ({"status": "archived"}, "invalid_status"),
    ({"teacher_id": 9999}, "invalid_teacher_id"),
    ({"classroom_id": 9999}, "invalid_classroom_id"),
    ({"start_date": "2026-12-01", "end_date": "2026-10-01"}, "end_before_start"),
    ({"meeting_days": "mon"}, "invalid_meeting_days"),
    ({"meeting_days": ["mon", "funday"]}, "invalid_meeting_days"),
    ({"start_time": "9:00"}, "invalid_time"),
    ({"end_time": "24:00"}, "invalid_time"),
    ({"start_time": "18:00", "end_time": "18:00"}, "end_time_before_start"),
    ({"start_time": "18:00", "end_time": "09:00"}, "end_time_before_start"),
])
def test_create_validation(client, admin_headers, payload, fields, error):
    resp = client.post("/admin/cohorts", headers=admin_headers, json=payload(**fields))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    assert Cohort.query.count() == 0


def test_create_invalid_date_names_field(client, admin_headers, payload):
    resp = client.post("/admin/cohorts", headers=admin_headers,
                       json=payload(end_date="December"))
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "invalid_date", "field": "end_date"}


def test_create_invalid_time_names_field(client, admin_headers, payload):
    resp = client.post("/admin/cohorts", headers=admin_headers,
                       json=payload(start_time="10:00", end_time="25:00"))
    assert resp.get_json() == {"error": "invalid_time", "field": "end_time"}


def test_create_invalid_meeting_days_lists_valid(client, admin_headers, payload):
    body = client.post("/admin/cohorts", headers=admin_headers,
                       json=payload(meeting_days=["x"])).get_json()
    assert body["valid"] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def test_create_rejects_unknown_parent_cohort(client, admin_headers, payload):
    resp = client.post("/admin/cohorts", headers=admin_headers,
                       json=payload(parent_cohort_id=9999))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_parent_cohort_id"


# ---------------------------------------------------------------- double booking
@pytest.fixture
def booked(client, admin_headers, payload, make_teacher, make_classroom):
    """An existing cohort: teacher + room, Mon/Wed 18:00-20:00, Oct-Dec."""
    teacher, _ = make_teacher()
    room = make_classroom()
    resp = client.post("/admin/cohorts", headers=admin_headers, json=payload(
        teacher_id=teacher.actor_id, classroom_id=room.id,
        meeting_days=["mon", "wed"], start_time="18:00", end_time="20:00",
    ))
    assert resp.status_code == 201
    return {"cohort_id": resp.get_json()["id"], "teacher_id": teacher.actor_id,
            "classroom_id": room.id}


def test_teacher_double_booking_is_blocked(client, admin_headers, payload, booked):
    resp = client.post("/admin/cohorts", headers=admin_headers, json=payload(
        name="Clash", teacher_id=booked["teacher_id"], start_date="2026-11-01",
        end_date="2027-01-01", meeting_days=["wed"], start_time="19:00", end_time="21:00",
    ))
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["error"] == "teacher_double_booked"
    assert body["conflict"]["cohort_id"] == booked["cohort_id"]
    assert body["conflict"]["meeting_days"] == ["mon", "wed"]
    assert body["conflict"]["start_time"] == "18:00"
    assert Cohort.query.count() == 1


def test_classroom_double_booking_is_blocked(client, admin_headers, payload, booked):
    resp = client.post("/admin/cohorts", headers=admin_headers, json=payload(
        name="Clash", classroom_id=booked["classroom_id"],
        meeting_days=["mon"], start_time="17:00", end_time="18:30",
    ))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "classroom_double_booked"
    assert resp.get_json()["conflict"]["cohort_id"] == booked["cohort_id"]


def test_unknown_days_or_times_assume_a_clash(client, admin_headers, payload, booked):
    resp = client.post("/admin/cohorts", headers=admin_headers,
                       json=payload(name="Vague", teacher_id=booked["teacher_id"]))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "teacher_double_booked"


@pytest.mark.parametrize("fields", [
    {"meeting_days": ["tue", "thu"], "start_time": "18:00", "end_time": "20:00"},
    {"meeting_days": ["mon"], "start_time": "20:00", "end_time": "21:00"},  # back-to-back
    {"meeting_days": ["mon"], "start_time": "09:00", "end_time": "12:00"},
    {"start_date": "2027-01-01", "end_date": "2027-03-01"},
    {"start_date": None, "end_date": None},  # undated cohorts are never checked
])
def test_non_overlapping_bookings_are_allowed(client, admin_headers, payload, booked, fields):
    data = payload(name="Other", teacher_id=booked["teacher_id"],
                   classroom_id=booked["classroom_id"])
    data.update(fields)
    resp = client.post("/admin/cohorts", headers=admin_headers, json=data)
    assert resp.status_code == 201, resp.get_json()


def test_updating_a_cohort_does_not_clash_with_itself(client, admin_headers, booked):
    resp = client.patch(f"/admin/cohorts/{booked['cohort_id']}", headers=admin_headers,
                        json={"end_time": "21:00"})
    assert resp.status_code == 200
    assert resp.get_json()["end_time"] == "21:00"


def test_update_into_a_clash_is_blocked(client, admin_headers, payload, booked, db):
    resp = client.post("/admin/cohorts", headers=admin_headers, json=payload(
        name="Other", teacher_id=booked["teacher_id"], meeting_days=["fri"],
        start_time="18:00", end_time="20:00",
    ))
    other_id = resp.get_json()["id"]
    resp = client.patch(f"/admin/cohorts/{other_id}", headers=admin_headers,
                        json={"meeting_days": ["fri", "mon"]})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "teacher_double_booked"
    db.session.rollback()  # requests share the fixture's app context; mimic teardown
    assert _fresh(db, Cohort, other_id).meeting_days == ["fri"]


# ---------------------------------------------------------------- update
def test_update_cohort(client, sales, make_cohort, db):
    _, headers = sales
    cid = make_cohort(status="draft").id
    resp = client.patch(f"/admin/cohorts/{cid}", headers=headers, json={
        "status": "open", "name": "Renamed", "capacity": 3, "graduation_date": "2026-12-10",
        "id": 555,
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == cid
    assert body["status"] == "open"
    assert body["name"] == "Renamed"
    assert body["graduation_date"] == "2026-12-10"
    assert _fresh(db, Cohort, cid).capacity == 3


def test_update_can_clear_dates(client, admin_headers, make_cohort, db):
    cid = make_cohort().id
    resp = client.patch(f"/admin/cohorts/{cid}", headers=admin_headers,
                        json={"start_date": None, "end_date": ""})
    assert resp.status_code == 200
    cohort = _fresh(db, Cohort, cid)
    assert cohort.start_date is None and cohort.end_date is None


@pytest.mark.parametrize("fields,error", [
    ({"status": "bogus"}, "invalid_status"),
    ({"name": None}, "name_required"),
    ({"end_date": "2020-01-01"}, "end_before_start"),
    ({"start_date": "2026-13-01"}, "invalid_date"),
])
def test_update_validation(client, admin_headers, make_cohort, db, fields, error):
    cohort = make_cohort(status="open")
    cid, name = cohort.id, cohort.name
    resp = client.patch(f"/admin/cohorts/{cid}", headers=admin_headers, json=fields)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    db.session.rollback()  # requests share the fixture's app context; mimic teardown
    cohort = _fresh(db, Cohort, cid)
    assert cohort.status == "open" and cohort.name == name


@pytest.mark.parametrize("field,error", [
    ("course_id", "invalid_course_id"),
    ("teacher_id", "invalid_teacher_id"),
    ("classroom_id", "invalid_classroom_id"),
])
def test_update_rejects_unknown_references(client, admin_headers, make_cohort, field, error):
    cohort = make_cohort()
    resp = client.patch(f"/admin/cohorts/{cohort.id}", headers=admin_headers,
                        json={field: 9999})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == error


def test_update_unknown_is_404(client, admin_headers):
    resp = client.patch("/admin/cohorts/9999", headers=admin_headers, json={"name": "X"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------- delete
def test_delete_cohort_and_its_enrollments(client, sales, make_cohort, make_student, db):
    _, headers = sales
    cid = make_cohort().id
    student, _ = make_student()
    assert _enroll(client, headers, cid, student.actor_id).status_code == 201

    resp = client.delete(f"/admin/cohorts/{cid}", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "deleted"}
    assert _fresh(db, Cohort, cid) is None
    assert Enrollment.query.count() == 0


def test_delete_unknown_is_404(client, admin_headers):
    resp = client.delete("/admin/cohorts/9999", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------- enroll
def test_staff_enroll_records_provenance(client, sales, make_cohort, make_student, db):
    staff, headers = sales
    cohort = make_cohort(status="open")
    student, _ = make_student()
    resp = _enroll(client, headers, cohort.id, student.actor_id)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "active"
    assert body["student_id"] == student.actor_id
    assert body["course_id"] == cohort.course_id
    assert body["created_via"] == "admin"
    assert body["created_by_admin_id"] == staff.actor_id
    assert db.session.get(Enrollment, body["id"]).cohort_id == cohort.id


def test_staff_may_enroll_into_closed_cohort(client, admin_headers, make_cohort, make_student):
    cohort = make_cohort(status="closed")
    student, _ = make_student()
    assert _enroll(client, admin_headers, cohort.id, student.actor_id).status_code == 201


def test_enroll_into_draft_is_409(client, admin_headers, make_cohort, make_student):
    cohort = make_cohort(status="draft")
    student, _ = make_student()
    resp = _enroll(client, admin_headers, cohort.id, student.actor_id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "cohort_not_open"
    assert Enrollment.query.count() == 0


@pytest.mark.parametrize("payload", [{}, {"student_id": None}, {"student_id": 0}])
def test_enroll_requires_student_id(client, admin_headers, make_cohort, payload):
    cohort = make_cohort()
    resp = client.post(f"/admin/cohorts/{cohort.id}/enroll", headers=admin_headers,
                       json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "student_id_required"


def test_enroll_unknown_student_is_404(client, admin_headers, make_cohort):
    cohort = make_cohort()
    resp = _enroll(client, admin_headers, cohort.id, 9999)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "student_not_found"


def test_enroll_unknown_cohort_is_404(client, admin_headers, make_student):
    student, _ = make_student()
    resp = _enroll(client, admin_headers, 9999, student.actor_id)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_enroll_twice_is_409(client, admin_headers, make_cohort, make_student):
    cohort = make_cohort()
    student, _ = make_student()
    _enroll(client, admin_headers, cohort.id, student.actor_id)
    resp = _enroll(client, admin_headers, cohort.id, student.actor_id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "already_enrolled"
    assert Enrollment.query.count() == 1


def test_enroll_into_full_cohort_is_409(client, admin_headers, make_cohort, make_student):
    cohort = make_cohort(capacity=1)
    first, _ = make_student()
    second, _ = make_student()
    assert _enroll(client, admin_headers, cohort.id, first.actor_id).status_code == 201
    resp = _enroll(client, admin_headers, cohort.id, second.actor_id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "cohort_full"


def test_enroll_reactivates_cancelled_enrollment(client, admin_headers, make_cohort,
                                                 make_student, db):
    cohort = make_cohort()
    student, _ = make_student()
    first_id = _enroll(client, admin_headers, cohort.id, student.actor_id).get_json()["id"]
    client.delete(f"/admin/cohorts/{cohort.id}/students/{student.actor_id}",
                  headers=admin_headers)
    resp = _enroll(client, admin_headers, cohort.id, student.actor_id)
    assert resp.status_code == 201
    assert resp.get_json()["id"] == first_id
    assert resp.get_json()["status"] == "active"
    assert Enrollment.query.count() == 1


def test_reactivation_respects_capacity(client, admin_headers, make_cohort, make_student):
    cohort = make_cohort(capacity=1)
    first, _ = make_student()
    second, _ = make_student()
    _enroll(client, admin_headers, cohort.id, first.actor_id)
    client.delete(f"/admin/cohorts/{cohort.id}/students/{first.actor_id}",
                  headers=admin_headers)
    assert _enroll(client, admin_headers, cohort.id, second.actor_id).status_code == 201
    resp = _enroll(client, admin_headers, cohort.id, first.actor_id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "cohort_full"


# ---------------------------------------------------------------- roster
def test_roster_lists_only_active(client, sales, make_cohort, make_student):
    _, headers = sales
    cohort = make_cohort()
    stay, _ = make_student(first_name="Anu", last_name="Bat")
    leave, _ = make_student()
    _enroll(client, headers, cohort.id, stay.actor_id)
    _enroll(client, headers, cohort.id, leave.actor_id)
    client.delete(f"/admin/cohorts/{cohort.id}/students/{leave.actor_id}", headers=headers)

    resp = client.get(f"/admin/cohorts/{cohort.id}/students", headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["cohort_id"] == cohort.id
    assert body["count"] == 1
    assert body["students"][0]["student_id"] == stay.actor_id
    assert body["students"][0]["student"]["name"] == "Anu Bat"


def test_roster_unknown_cohort_is_404(client, admin_headers):
    resp = client.get("/admin/cohorts/9999/students", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------- remove
def test_remove_student_cancels_enrollment(client, sales, make_cohort, make_student, db):
    _, headers = sales
    cohort = make_cohort(capacity=1)
    student, _ = make_student()
    eid = _enroll(client, headers, cohort.id, student.actor_id).get_json()["id"]

    resp = client.delete(f"/admin/cohorts/{cohort.id}/students/{student.actor_id}",
                         headers=headers)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "removed"}
    assert _fresh(db, Enrollment, eid).status == "cancelled"  # history kept
    body = client.get(f"/admin/cohorts/{cohort.id}", headers=headers).get_json()
    assert body["enrolled_count"] == 0
    assert body["seats_available"] == 1


def test_remove_not_enrolled_is_404(client, admin_headers, make_cohort, make_student):
    cohort = make_cohort()
    student, _ = make_student()
    resp = client.delete(f"/admin/cohorts/{cohort.id}/students/{student.actor_id}",
                         headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_enrolled"
