"""Installment plans (BE-02) and the price frozen at enrolment (BE-28)."""
from datetime import date
from decimal import Decimal

import pytest

from app.models import Enrollment, PaymentInstallment, StudentLedger


@pytest.fixture
def finance(make_staff):
    return make_staff("finance")[1]


@pytest.fixture
def enrolled(client, db, make_student, make_cohort, make_course, admin_headers):
    """``enrolled(cohort_fields, **course)`` -> Enrollment, made by staff via the API."""
    def _make(cohort_fields=None, **course_fields):
        account, _ = make_student()
        cohort = make_cohort(course=make_course(**course_fields), **(cohort_fields or {}))
        resp = client.post(f"/admin/cohorts/{cohort.id}/enroll", headers=admin_headers,
                           json={"student_id": account.actor_id})
        assert resp.status_code == 201
        return db.session.get(Enrollment, resp.get_json()["id"])

    return _make


def _plan(db, enr):
    db.session.expire_all()
    return [(i.seq, i.due_date.isoformat(), i.amount, i.status) for i in
            PaymentInstallment.query.filter_by(enrollment_id=enr.id)
            .order_by(PaymentInstallment.seq)]


def _ledger(db, enr):
    db.session.expire_all()
    return StudentLedger.query.filter_by(enrollment_id=enr.id).one()


# ------------------------------------------------------------------- default plan
def test_enrolment_lays_out_the_course_rule(db, enrolled):
    enr = enrolled({"start_date": date(2026, 1, 31)}, installment_count=3,
                   installment_interval_months=1)
    assert _plan(db, enr) == [
        (1, "2026-01-31", Decimal("333334.00"), "pending"),
        (2, "2026-02-28", Decimal("333333.00"), "pending"),
        (3, "2026-03-31", Decimal("333333.00"), "pending"),
    ]
    ledger = _ledger(db, enr)
    assert (ledger.total_due, ledger.balance) == (Decimal("1000000.00"), Decimal("1000000.00"))
    assert ledger.next_due_date == date(2026, 1, 31)


def test_default_rule_is_one_payment_of_the_discounted_price(db, enrolled):
    enr = enrolled(discount_percent=10)
    assert _plan(db, enr) == [(1, "2026-10-01", Decimal("900000.00"), "pending")]
    assert db.session.get(Enrollment, enr.id).price_amount == Decimal("900000.00")


def test_free_course_gets_no_plan_and_owes_nothing(db, enrolled):
    enr = enrolled(price_amount=None)
    assert _plan(db, enr) == []
    assert _ledger(db, enr).balance == 0


def test_student_sees_the_plan_on_me_ledger(client, db, make_student, make_cohort, make_course):
    account, headers = make_student()
    cohort = make_cohort(course=make_course(installment_count=2))
    client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
    [row] = client.get("/me/ledger", headers=headers).get_json()["enrollments"]
    assert [i["amount"] for i in row["installments"]] == [500000.0, 500000.0]
    assert row["next_due_date"] == "2026-10-01" and row["balance"] == 1000000.0


def test_reactivation_keeps_the_plan(client, db, make_student, make_cohort):
    account, headers = make_student()
    cohort = make_cohort()
    client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
    client.delete(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert client.post(f"/cohorts/{cohort.id}/enroll", headers=headers).status_code == 201
    assert PaymentInstallment.query.count() == 1


@pytest.mark.parametrize("field, value", [
    ("installment_count", 0), ("installment_count", 25), ("installment_count", "3"),
    ("installment_interval_months", 13), ("installment_count", True),
])
def test_course_rule_is_validated(client, admin_headers, make_course, field, value):
    course = make_course()
    resp = client.patch(f"/courses/{course.id}", headers=admin_headers, json={field: value})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == f"invalid_{field}"


# ------------------------------------------------------------------- finance edits
def test_finance_edits_adds_waives_and_deletes(client, db, finance, enrolled):
    enr = enrolled(installment_count=2)
    first, second = PaymentInstallment.query.filter_by(enrollment_id=enr.id).order_by(
        PaymentInstallment.seq).all()

    resp = client.patch(f"/admin/installments/{second.id}", headers=finance,
                        json={"amount": 400_000, "due_date": "2026-12-15"})
    assert resp.status_code == 200 and resp.get_json()["amount"] == 400000.0
    added = client.post(f"/admin/enrollments/{enr.id}/installments", headers=finance,
                        json={"amount": 100_000, "due_date": "2027-01-15"})
    assert added.status_code == 201 and added.get_json()["seq"] == 3
    assert _ledger(db, enr).total_due == Decimal("1000000.00")

    waived = client.post(f"/admin/installments/{first.id}/waive", headers=finance)
    assert waived.get_json()["status"] == "waived"
    ledger = _ledger(db, enr)
    assert (ledger.total_due, ledger.next_due_date) == (Decimal("500000.00"), date(2026, 12, 15))

    resp = client.delete(f"/admin/installments/{added.get_json()['id']}", headers=finance)
    assert resp.status_code == 200
    assert _ledger(db, enr).total_due == Decimal("400000.00")

    body = client.get(f"/admin/enrollments/{enr.id}/installments", headers=finance).get_json()
    assert [i["status"] for i in body["installments"]] == ["waived", "pending"]
    assert body["price_amount"] == 1000000.0 and body["ledger"]["balance"] == 400000.0


def test_settled_installments_are_history(client, db, finance, enrolled):
    enr = enrolled()
    inst = PaymentInstallment.query.filter_by(enrollment_id=enr.id).one()
    client.post(f"/admin/installments/{inst.id}/waive", headers=finance)
    for method, url, payload in (("patch", f"/admin/installments/{inst.id}", {"amount": 1}),
                                 ("delete", f"/admin/installments/{inst.id}", None),
                                 ("post", f"/admin/installments/{inst.id}/waive", None)):
        resp = getattr(client, method)(url, headers=finance, json=payload)
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "installment_settled", "installment_status": "waived"}


def test_installment_with_an_invoice_cannot_be_deleted(client, db, gateways, finance, enrolled):
    enr = enrolled()
    inst = PaymentInstallment.query.filter_by(enrollment_id=enr.id).one()
    client.post("/admin/invoices", headers=finance,
                json={"provider": "qpay", "installment_id": inst.id})
    resp = client.delete(f"/admin/installments/{inst.id}", headers=finance)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "installment_has_invoices"


def test_default_plan_for_an_older_enrollment(client, db, finance, make_student, make_cohort):
    account, _ = make_student()
    cohort = make_cohort()
    enr = Enrollment(cohort_id=cohort.id, student_id=account.actor_id,
                     course_id=cohort.course_id, status="active")
    db.session.add(enr)
    db.session.commit()
    url = f"/admin/enrollments/{enr.id}/installments/default"
    resp = client.post(url, headers=finance)
    assert resp.status_code == 201
    assert [i["amount"] for i in resp.get_json()["installments"]] == [1000000.0]
    again = client.post(url, headers=finance)
    assert again.status_code == 409 and again.get_json()["error"] == "plan_exists"


@pytest.mark.parametrize("payload, error", [
    ({"amount": 0, "due_date": "2026-11-01"}, "amount_must_be_positive"),
    ({"amount": 1000, "due_date": "soon"}, "invalid_date"),
])
def test_add_installment_validates(client, finance, enrolled, payload, error):
    enr = enrolled()
    resp = client.post(f"/admin/enrollments/{enr.id}/installments", headers=finance,
                       json=payload)
    assert resp.status_code == 400 and resp.get_json()["error"] == error


def test_plan_routes_are_permission_gated(client, enrolled, make_staff):
    enr = enrolled()
    inst = PaymentInstallment.query.filter_by(enrollment_id=enr.id).one()
    sales = make_staff("sales_enrollment")[1]
    assert client.get(f"/admin/enrollments/{enr.id}/installments",
                      headers=sales).status_code == 403
    assert client.post(f"/admin/installments/{inst.id}/waive", headers=sales).status_code == 403
    assert client.get("/admin/enrollments/9999/installments",
                      headers=make_staff("finance")[1]).status_code == 404


# ------------------------------------------------------------------- frozen price
def test_price_edit_after_enrolment_moves_nothing(client, db, admin_headers, enrolled):
    from app.models import StudentContract
    from app.services.contracts import core

    enr = enrolled(contract_template_key="courses/1/contract_template.pdf")
    resp = client.patch(f"/courses/{enr.course_id}", headers=admin_headers,
                        json={"price_amount": 2_000_000})
    assert resp.status_code == 200
    recomputed = client.post(f"/admin/ledger/{enr.id}/recompute", headers=admin_headers)
    assert recomputed.get_json()["total_due"] == 1000000.0
    core.sync(student_id=enr.student_id)
    contract = StudentContract.query.filter_by(enrollment_id=enr.id).one()
    assert core.finance(contract)["total_due"] == 1000000.0
