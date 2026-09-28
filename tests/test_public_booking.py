"""Public enrolment funnel, steps 2–3: schedules with their seat maps, and booking."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import public_helpers
import pytest
from public_helpers import _book, _booking, _legacy

from app.models import ClassroomRequest, SeatBooking

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
lead = public_helpers.lead
make_promotion = public_helpers.make_promotion
published = public_helpers.published


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
