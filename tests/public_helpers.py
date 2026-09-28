"""Shared fixtures and helpers for the public enrolment / checkout tests."""
import pytest

from app.models import CohortLegacySchedule, Promotion, SeatBooking

LEAD = {"name": "Бат Дорж", "email": "Bat@Example.MN", "phone_num": "99112233"}
CHECKOUT_LEAD = {"name": "Бат Дорж", "email": "bat@example.mn", "phone_num": "99112233",
                 "register_num": "УБ12345678"}
COMPANY = {"tin": "12345678901", "name": "Жишээ ХХК", "found": True}


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


def _status(client, token):
    resp = client.get(f"/payments/invoice/status?pt={token}")
    return resp.status_code, resp.get_json()


@pytest.fixture
def checkout(client, make_course, make_cohort):
    """``checkout(price=..., capacity=...)`` -> payment token of a fresh held seat."""

    def _make(price=1_000_000, capacity=10, cohort=None):
        if cohort is None:
            course = make_course(status="published", price_amount=price)
            cohort = make_cohort(course=course, capacity=capacity, name="Corporate Leaders")
        request_id = client.post("/classroom-requests", json=CHECKOUT_LEAD).get_json()["_id"]
        resp = client.post(f"/classroom-courses/{cohort.course_id}/bookings", json={
            "classroom_request_id": request_id, "classroom_course_schedule_id": cohort.id,
        })
        assert resp.status_code == 201, resp.get_json()
        return resp.get_json()["payment_token"]

    return _make


@pytest.fixture
def paid(client, gateways, checkout):
    """A settled QPay checkout's token."""

    def _make(**kwargs):
        token = checkout(**kwargs)
        client.get(f"/payments/qpay/invoice?pt={token}")
        gateways["qpay"].paid = True
        assert client.get(f"/payments/invoice/status?pt={token}").get_json()[
            "status_id"]["_id"] == 2
        gateways["qpay"].paid = False
        return token

    return _make


@pytest.fixture
def live_ebarimt(app, monkeypatch):
    """Leave temp mode and stand in for PosAPI. Returns the payloads it received."""
    monkeypatch.setitem(app.config, "EBARIMT_TEMP_MODE", False)
    sent = []

    def _create(self, payload):
        sent.append(payload)
        return {"id": f"DDTD{len(sent):04d}", "lottery": "AB123", "qrData": "qr",
                "date": "2026-09-28 12:00:00"}

    monkeypatch.setattr("app.ebarimt.posapi.PosAPIClient.create_receipt", _create)
    return sent


@pytest.fixture
def taxpayer(monkeypatch):
    """Stub the tax directory; ``taxpayer.found`` is what resolve() returns."""

    class Stub:
        found = dict(COMPANY)
        fail = None
        asked = []

    def _resolve(self, value):
        Stub.asked.append(value)
        if Stub.fail:
            raise Stub.fail
        return Stub.found

    monkeypatch.setattr("app.ebarimt.lookup.TaxpayerLookup.resolve", _resolve)
    return Stub
