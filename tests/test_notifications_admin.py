"""Staff announcements: POST /admin/notifications."""
import engagement_helpers
import pytest
from engagement_helpers import enroll

from app.models import Notification

klass = engagement_helpers.klass


def _send(client, headers, **data):
    return client.post("/admin/notifications", headers=headers, json=data)


def test_cohort_announcement_reaches_active_students_only(client, db, klass, make_staff,
                                                          make_student):
    cohort = klass["cohort"]
    dropped, _ = make_student()
    enroll(db, cohort, dropped, status="cancelled")
    second, s2_headers = make_student()
    enroll(db, cohort, second)
    _, headers = make_staff("sales_enrollment")
    resp = _send(client, headers, cohort_id=cohort.id, title=" Class moved ",
                 body="Room 2", data={"room": 2})
    assert resp.status_code == 201
    assert resp.get_json() == {"sent": 2}
    rows = Notification.query.order_by(Notification.account_id).all()
    assert {r.account_id for r in rows} == {klass["student"].id, second.id}
    assert rows[0].title == "Class moved"
    assert rows[0].kind == "announcement"
    assert rows[0].data == {"cohort_id": cohort.id, "room": 2}
    inbox = client.get("/me/notifications", headers=s2_headers).get_json()
    assert inbox["unread_count"] == 1


def test_announcement_to_named_accounts(client, admin_headers, make_teacher, make_student):
    teacher, _ = make_teacher()
    student, _ = make_student()
    resp = _send(client, admin_headers, account_ids=[teacher.id, str(student.id)], title="Hi")
    assert resp.get_json() == {"sent": 2}
    assert Notification.query.count() == 2


def test_empty_cohort_sends_nothing(client, admin_headers, make_cohort):
    resp = _send(client, admin_headers, cohort_id=make_cohort().id, title="Hi")
    assert resp.status_code == 201
    assert resp.get_json() == {"sent": 0}


@pytest.mark.parametrize("data,status,code", [
    ({"cohort_id": 1}, 400, "title_required"),
    ({"title": "  ", "cohort_id": 1}, 400, "title_required"),
    ({"title": "x" * 201, "cohort_id": 1}, 400, "title_too_long"),
    ({"title": "Hi"}, 400, "recipients_required"),
    ({"title": "Hi", "account_ids": []}, 400, "invalid_account_ids"),
    ({"title": "Hi", "account_ids": ["abc"]}, 400, "invalid_account_ids"),
    ({"title": "Hi", "account_ids": [999999]}, 400, "unknown_account_ids"),
    ({"title": "Hi", "cohort_id": 999999}, 404, "cohort_not_found"),
    ({"title": "Hi", "cohort_id": 1, "data": [1]}, 400, "invalid_data"),
    ({"title": "Hi", "cohort_id": 1, "body": 5}, 400, "invalid_body"),
])
def test_announcement_validation(client, admin_headers, data, status, code):
    resp = client.post("/admin/notifications", headers=admin_headers, json=data)
    assert resp.status_code == status
    assert resp.get_json()["error"] == code


def test_announcement_permissions(client, klass, make_staff):
    cohort_id = klass["cohort"].id
    for headers in (klass["t_headers"], klass["s_headers"], make_staff("finance")[1]):
        resp = _send(client, headers, cohort_id=cohort_id, title="Hi")
        assert resp.status_code == 403
    assert _send(client, None, cohort_id=cohort_id, title="Hi").status_code == 401
    assert Notification.query.count() == 0
