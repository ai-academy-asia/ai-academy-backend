"""Public enrolment funnel, steps 0–3 and 7: catalogue, lead, seats, booking, coupon."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models import (
    ClassroomRequest,
    CohortLegacySchedule,
    Promotion,
    SeatBooking,
)

LEAD = {"name": "Бат Дорж", "email": "Bat@Example.MN", "phone_num": "99112233"}


@pytest.fixture
def published(make_course):
    def _make(**fields):
        return make_course(**{"status": "published", **fields})

    return _make


@pytest.fixture
def lead(client):
    def _make(**fields):
        resp = client.post("/classroom-requests", json={**LEAD, **fields})
        assert resp.status_code == 201, resp.get_json()
        return resp.get_json()["_id"]

    return _make


@pytest.fixture
def make_promotion(db):
    def _make(code="SALE10", **fields):
        values = {"code": code, "name": "Sale", "discount_type": "percent",
                  "discount_value": 10}
        values.update(fields)
        promo = Promotion(**values)
        db.session.add(promo)
        db.session.commit()
        return promo

    return _make


def _legacy(db, cohort, legacy_id, kind="full", percent=100):
    row = CohortLegacySchedule(legacy_schedule_id=legacy_id, cohort_id=cohort.id,
                               kind=kind, charge_percent=percent)
    db.session.add(row)
    db.session.commit()
    return row


def _book(client, course_id, request_id, schedule_id, **extra):
    return client.post(
        f"/classroom-courses/{course_id}/bookings",
        json={"classroom_request_id": request_id,
              "classroom_course_schedule_id": schedule_id, **extra},
    )


def _booking(token):
    return SeatBooking.query.filter_by(payment_token=token).one()


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


@pytest.mark.xfail(strict=True, reason="apply_coupon compares the public (legacy) course id "
                   "against Promotion.course_id (our id) without resolving it")
def test_coupon_scoped_to_course_accepts_its_legacy_id(client, lead, make_promotion, published):
    course = published(legacy_course_id=51)
    assert course.id != 51
    make_promotion(course_id=course.id)
    resp = client.post(f"/classroom-requests/{lead()}/coupon",
                       json={"promotion_code": "SALE10", "classroom_course_id": 51})
    assert resp.status_code == 200


# ------------------------------------------------------------------ schedules
def test_schedules_list_every_run_with_seat_map(client, published, make_cohort, lead, db):
    course = published(legacy_course_id=51, price_amount=500_000)
    run = make_cohort(course=course, capacity=4, legacy_schedule_id=700,
                      start_time="09:00", end_time="11:00", meeting_days=["sat"])
    other = make_cohort(course=course, start_date=date(2027, 1, 1), capacity=2)
    request_id = lead()
    for seat, status in ((1, "paid"), (2, "held")):
        db.session.add(SeatBooking(classroom_request_id=request_id, cohort_id=run.id,
                                   number_of_seat=seat, payment_token=f"pt_{seat}",
                                   status=status, amount=1,
                                   expires_at=datetime.utcnow() + timedelta(minutes=5)))
    db.session.add(SeatBooking(classroom_request_id=request_id, cohort_id=run.id,
                               number_of_seat=3, payment_token="pt_lapsed", status="held",
                               amount=1, expires_at=datetime.utcnow() - timedelta(minutes=1)))
    db.session.commit()

    resp = client.get("/classroom-courses/51/schedules")
    assert resp.status_code == 200
    first, second = resp.get_json()
    assert first["_id"] == 700 and second["_id"] == other.id
    assert first["classroom_course_id"] == 51
    assert first["schedule_date"] == "2026-10-01T09:00:00"
    assert first["schedule_days"] == "Бя"
    assert first["schedule_time"] == "09:00-11:00"
    assert first["seats"] == [1, 2, 3, 4]
    assert first["available_seats"] == [3, 4]
    assert [s["number_of_seat"] for s in first["paid_seats"]] == [1]
    assert [s["number_of_seat"] for s in first["locked_seats"]] == [2]
    assert first["price"] == 500_000
    assert second["available_seats"] == [1, 2]


def test_schedules_price_is_null_for_non_mnt_course(client, published, make_cohort):
    course = published(currency="USD", price_amount=1600)
    make_cohort(course=course)
    assert client.get(f"/classroom-courses/{course.id}/schedules").get_json()[0]["price"] is None


def test_schedules_404_unknown_course(client):
    resp = client.get("/classroom-courses/999/schedules")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "course_not_found"


# ------------------------------------------------------------------ bookings
def test_booking_holds_seat_and_mints_unique_token(client, published, make_cohort, lead):
    course = published(price_amount=1_000_000, discount_percent=10)
    cohort = make_cohort(course=course, capacity=3)
    request_id = lead()

    resp = _book(client, course.id, request_id, cohort.id, number_of_seat=2, amount=1)
    assert resp.status_code == 201
    token = resp.get_json()["payment_token"]
    assert token.startswith("pt_") and list(resp.get_json()) == ["payment_token"]

    booking = _booking(token)
    assert booking.status == "held"
    assert booking.number_of_seat == 2
    assert booking.cohort_id == cohort.id
    assert booking.amount == Decimal("900000.00")  # client amount ignored
    assert booking.promotion_code is None
    assert timedelta(minutes=29) < booking.expires_at - datetime.utcnow() <= timedelta(minutes=30)
    assert ClassroomRequest.query.filter_by(id=request_id).one().status == "booked"

    again = _book(client, course.id, lead(), cohort.id, number_of_seat=2)
    assert again.status_code == 201
    second = _booking(again.get_json()["payment_token"])
    assert second.number_of_seat == 1  # requested seat taken -> next free
    assert second.payment_token != token


def test_booking_respects_seat_hold_minutes(client, app, published, make_cohort, lead,
                                            monkeypatch):
    monkeypatch.setitem(app.config, "SEAT_HOLD_MINUTES", 5)
    cohort = make_cohort(course=published())
    token = _book(client, cohort.course_id, lead(), cohort.id).get_json()["payment_token"]
    assert _booking(token).expires_at - datetime.utcnow() <= timedelta(minutes=5)


def test_booking_409s_when_run_is_full(client, published, make_cohort, lead):
    cohort = make_cohort(course=published(), capacity=1)
    assert _book(client, cohort.course_id, lead(), cohort.id).status_code == 201
    resp = _book(client, cohort.course_id, lead(), cohort.id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "no_seats_left"
    assert SeatBooking.query.count() == 1


def test_booking_reuses_seat_of_lapsed_hold(client, published, make_cohort, lead, db):
    cohort = make_cohort(course=published(), capacity=1)
    token = _book(client, cohort.course_id, lead(), cohort.id).get_json()["payment_token"]
    stale = _booking(token)
    stale.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()

    resp = _book(client, cohort.course_id, lead(), cohort.id)
    assert resp.status_code == 201
    assert _booking(token).status == "released"
    assert _booking(resp.get_json()["payment_token"]).number_of_seat == 1


def test_booking_applies_valid_promotion(client, published, make_cohort, lead, make_promotion):
    course = published(price_amount=1_000_000)
    cohort = make_cohort(course=course)
    make_promotion(code="SALE10", name="Намар", discount_value=10)
    make_promotion(code="FLAT", discount_type="amount", discount_value=2_000_000)

    token = _book(client, course.id, lead(), cohort.id,
                  promotion_code="SALE10").get_json()["payment_token"]
    booking = _booking(token)
    assert booking.amount == Decimal("900000.00")
    assert booking.promotion_code == "SALE10"
    assert booking.promotion_name == "Намар"
    assert booking.promotion_amount == Decimal("100000.00")

    capped = _booking(_book(client, course.id, lead(), cohort.id,
                            promotion_code="FLAT").get_json()["payment_token"])
    assert capped.amount == Decimal("0.00")
    assert capped.promotion_amount == Decimal("1000000.00")


def test_booking_ignores_invalid_promotion(client, published, make_cohort, lead, make_promotion):
    course = published(price_amount=1_000_000)
    cohort = make_cohort(course=course)
    make_promotion(code="OLD", expires_at=datetime.utcnow() - timedelta(days=1))
    make_promotion(code="ELSEWHERE", course_id=published().id)

    for code in ("NOPE", "OLD", "ELSEWHERE"):
        booking = _booking(_book(client, course.id, lead(), cohort.id,
                                 promotion_code=code).get_json()["payment_token"])
        assert booking.amount == Decimal("1000000.00")
        assert booking.promotion_code is None
        assert booking.promotion_amount is None


def test_booking_by_legacy_ids_bills_deposit_share(client, published, make_cohort, lead, db,
                                                   make_promotion):
    course = published(price_amount=1_000_000, legacy_course_id=51)
    cohort = make_cohort(course=course, legacy_schedule_id=700)
    _legacy(db, cohort, 701, kind="deposit", percent=50)
    _legacy(db, cohort, 703, kind="promo_deposit", percent=30)
    make_promotion(code="SALE10", discount_value=10)

    full = _book(client, 51, lead(), 700)
    assert full.status_code == 201
    assert _booking(full.get_json()["payment_token"]).amount == Decimal("1000000.00")

    deposit = _booking(_book(client, 51, lead(), 701).get_json()["payment_token"])
    assert deposit.cohort_id == cohort.id
    assert deposit.amount == Decimal("500000.00")

    # promotion first, then the deposit share of what is left
    promo_deposit = _booking(_book(client, 51, lead(), 703,
                                   promotion_code="SALE10").get_json()["payment_token"])
    assert promo_deposit.amount == Decimal("270000.00")


def test_booking_by_our_own_ids(client, published, make_cohort, lead):
    course = published(legacy_course_id=51)
    cohort = make_cohort(course=course)
    resp = _book(client, course.id, lead(), cohort.id)
    assert resp.status_code == 201


def test_booking_404s_unknown_request(client, published, make_cohort):
    cohort = make_cohort(course=published())
    for request_id in (None, 999):
        resp = _book(client, cohort.course_id, request_id, cohort.id)
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "classroom_request_not_found"


def test_booking_404s_unknown_or_mismatched_schedule(client, published, make_cohort, lead):
    course = published()
    other_run = make_cohort(course=published())
    request_id = lead()
    for schedule_id in (None, 999, "abc", other_run.id):
        resp = _book(client, course.id, request_id, schedule_id)
        assert resp.status_code == 404, schedule_id
        assert resp.get_json()["error"] == "schedule_not_found"
    assert SeatBooking.query.count() == 0


@pytest.mark.parametrize("status", ["draft", "closed"])
def test_booking_409s_on_run_not_on_sale(client, published, make_cohort, lead, status):
    cohort = make_cohort(course=published(), status=status)
    resp = _book(client, cohort.course_id, lead(), cohort.id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "schedule_not_bookable"


def test_booking_409s_when_course_not_priced_in_mnt(client, published, make_cohort, lead):
    cohort = make_cohort(course=published(currency="USD", price_amount=1600))
    request_id = lead()
    resp = _book(client, cohort.course_id, request_id, cohort.id)
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "price_not_in_mnt", "currency": "USD"}
    assert SeatBooking.query.count() == 0
    assert ClassroomRequest.query.filter_by(id=request_id).one().status == "new"
