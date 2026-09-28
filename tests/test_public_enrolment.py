"""Public enrolment funnel, steps 0–1 and 7: catalogue, classroom courses, lead, coupon."""
from datetime import date, datetime, timedelta

import public_helpers
import pytest
from public_helpers import LEAD, _legacy

from app.models import ClassroomRequest

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
lead = public_helpers.lead
make_promotion = public_helpers.make_promotion
published = public_helpers.published


# ------------------------------------------------------------------ programmes
def test_programmes_lists_only_published_courses_in_sort_order(client, published, make_course):
    make_course(status="draft")
    second = published(sort_order=2, title_mn="Хоёр")
    first = published(sort_order=1, title_mn="Нэг")
    unsorted = published(sort_order=None)

    resp = client.get("/programmes")
    assert resp.status_code == 200
    assert [p["id"] for p in resp.get_json()] == [first.id, second.id, unsorted.id]


def test_programme_card_books_against_next_upcoming_run(client, published, make_cohort, db):
    course = published(price_amount=1_000_000, discount_percent=20, level="adult",
                       format="in_person", legacy_course_id=51, title_en="Eng")
    make_cohort(course=course, start_date=date(2020, 1, 1), end_date=date(2020, 3, 1))
    later = make_cohort(course=course, start_date=date(2031, 1, 1), end_date=date(2031, 3, 1))
    soon = make_cohort(course=course, start_date=date(2030, 1, 1), end_date=date(2030, 3, 1),
                       legacy_schedule_id=700, capacity=5, meeting_days=["mon", "wed"],
                       start_time="18:00", end_time="20:00")
    make_cohort(course=course, status="draft", start_date=date(2029, 1, 1))
    _legacy(db, soon, 701, kind="deposit", percent=50)
    _legacy(db, soon, 702, kind="promo")
    assert later.id

    card = client.get("/programmes").get_json()[0]
    assert card["id"] == course.id
    assert card["classroom_course_id"] == 51
    assert card["schedule_id"] == 700
    assert card["fee"] == 1_000_000 and card["final_fee"] == 800_000
    assert card["discount_percent"] == 20
    assert card["max_students"] == 5 and card["enrolled"] == 0
    assert card["audience"] == "adult" and card["delivery"] == "inclass"
    assert card["session"] == "evening"
    assert card["active_days"] == ["Да", "Лх"]
    assert card["time_label"] == "18:00–20:00"
    assert card["start_date"].startswith("2030-01-01")
    assert card["deposit_schedule_id"] == 701
    assert card["promo_schedule_id"] == 702
    assert card["advance_payment_percent"] == 50
    assert "_seats" not in card

    assert client.get("/programmes?locale=en").get_json()[0]["title"] == "Eng"


def test_programme_without_open_run_is_not_bookable(client, published):
    published(capacity=12)
    card = client.get("/programmes").get_json()[0]
    assert card["schedule_id"] is None
    assert card["max_students"] == 12
    assert card["deposit_schedule_id"] is None


# ------------------------------------------------------------------ classroom courses
def test_classroom_courses_lists_published_in_frontend_shape(client, published, make_course):
    make_course(status="draft")
    course = published(price_amount=1_000_000, discount_percent=10, level="corporate",
                       format="online", legacy_course_id=77)

    resp = client.get("/classroom-courses")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) == 1
    assert rows[0]["_id"] == 77
    assert rows[0]["price"] == 900_000
    assert rows[0]["type"] == "Company"
    assert rows[0]["format"] == "Онлайн"
    assert rows[0]["locale_uuid"] == course.slug


def test_classroom_course_resolves_legacy_and_own_ids(client, published):
    legacy = published(legacy_course_id=51)
    own = published()
    assert client.get("/classroom-courses/51").get_json()["_id"] == 51
    assert client.get(f"/classroom-courses/{own.id}").get_json()["_id"] == own.id
    assert legacy.id != 51


def test_classroom_course_404s_unknown_or_unpublished(client, make_course):
    draft = make_course(status="draft")
    for course_id in (9999, draft.id):
        resp = client.get(f"/classroom-courses/{course_id}")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "course_not_found"


# ------------------------------------------------------------------ classroom requests
def test_create_request_stores_normalised_lead(client, published):
    course = published(legacy_course_id=51)
    resp = client.post("/classroom-requests", json={
        **LEAD, "classroom_course_id": 51, "register_num": "уб12345678",
        "phone_num2": " 88 ", "student_plan": "x" * 5000,
    })
    assert resp.status_code == 201
    row = ClassroomRequest.query.filter_by(id=resp.get_json()["_id"]).one()
    assert resp.get_json() == {"_id": row.id}
    assert row.course_id == course.id
    assert row.email == "bat@example.mn"
    assert row.register_num == "УБ12345678"
    assert row.phone_num2 == "88"
    assert len(row.student_plan) == 2000
    assert row.status == "new"


def test_create_request_without_course_is_allowed(client):
    resp = client.post("/classroom-requests", json=LEAD)
    assert resp.status_code == 201
    assert ClassroomRequest.query.filter_by(id=resp.get_json()["_id"]).one().course_id is None


@pytest.mark.parametrize("payload, code", [
    ({}, "name_email_phone_required"),
    ({**LEAD, "name": " "}, "name_email_phone_required"),
    ({**LEAD, "phone_num": ""}, "name_email_phone_required"),
    ({**LEAD, "email": "not-an-email"}, "invalid_email"),
    ({**LEAD, "register_num": "AB12345678"}, "invalid_register_num"),
    ({**LEAD, "register_num": "УБ1234"}, "invalid_register_num"),
])
def test_create_request_validates_fields(client, payload, code):
    resp = client.post("/classroom-requests", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == code
    assert ClassroomRequest.query.count() == 0


def test_create_request_404s_unknown_course(client):
    resp = client.post("/classroom-requests", json={**LEAD, "classroom_course_id": 4242})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "course_not_found"


# ------------------------------------------------------------------ coupon
def test_coupon_returns_valid_promotion(client, lead, make_promotion, published):
    make_promotion(code="SALE10", name="Намрын хямдрал", discount_value=10)
    course = published()
    make_promotion(code="SCOPED", discount_type="amount", discount_value=50000,
                   course_id=course.id)
    request_id = lead()

    resp = client.post(f"/classroom-requests/{request_id}/coupon",
                       json={"promotion_code": " SALE10 "})
    assert resp.status_code == 200
    assert resp.get_json() == {"name": "Намрын хямдрал", "discount_type": "percent",
                               "discount_value": 10.0}

    scoped = client.post(f"/classroom-requests/{request_id}/coupon",
                         json={"promotion_code": "SCOPED", "classroom_course_id": course.id})
    assert scoped.status_code == 200
    assert scoped.get_json()["discount_value"] == 50000.0


def test_coupon_404s_unknown_request(client, make_promotion):
    make_promotion()
    resp = client.post("/classroom-requests/999/coupon", json={"promotion_code": "SALE10"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "classroom_request_not_found"


@pytest.mark.parametrize("fields, body", [
    (None, {"promotion_code": "NOPE"}),
    (None, {}),
    ({"is_active": False}, {"promotion_code": "SALE10"}),
    ({"expires_at": datetime.utcnow() - timedelta(days=1)}, {"promotion_code": "SALE10"}),
    ({"starts_at": datetime.utcnow() + timedelta(days=1)}, {"promotion_code": "SALE10"}),
    ({"max_uses": 1, "used_count": 1}, {"promotion_code": "SALE10"}),
    ({"course_id": "OTHER"}, {"promotion_code": "SALE10"}),
])
def test_coupon_404s_invalid_codes(client, lead, make_promotion, published, fields, body):
    if fields is not None:
        if fields.get("course_id") == "OTHER":
            fields = {"course_id": published().id}
        make_promotion(**fields)
    resp = client.post(f"/classroom-requests/{lead()}/coupon", json=body)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "promotion_not_found"


def test_coupon_scoped_to_course_accepts_its_legacy_id(client, lead, make_promotion, published):
    course = published(legacy_course_id=51)
    assert course.id != 51
    make_promotion(course_id=course.id)
    resp = client.post(f"/classroom-requests/{lead()}/coupon",
                       json={"promotion_code": "SALE10", "classroom_course_id": 51})
    assert resp.status_code == 200
