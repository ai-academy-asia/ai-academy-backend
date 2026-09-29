"""The student's own money: GET /me/ledger, /me/invoices, /me/receipts[/<id>]."""
from datetime import date

import account_helpers

enroll = account_helpers.enroll
make_ledger = account_helpers.make_ledger
make_invoice = account_helpers.make_invoice
make_receipt = account_helpers.make_receipt


# ----------------------------------------------------------------- auth
def test_money_endpoints_need_a_student(client, make_teacher, make_staff):
    for path in ("/me/ledger", "/me/invoices", "/me/receipts", "/me/receipts/1"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=make_teacher()[1]).status_code == 403
        assert client.get(path, headers=make_staff("finance")[1]).status_code == 403


# ----------------------------------------------------------------- ledger
def test_ledger_lists_enrollments_with_installments(client, db, make_student, make_course,
                                                    make_cohort, enroll, make_ledger):
    from app.models import PaymentInstallment

    account, headers = make_student()
    course = make_course(title_en="Leaders")
    cohort = make_cohort(course=course, name="CL 2026-10")
    enr = enroll(account.actor_id, cohort)
    make_ledger(enr, due=1_000_000, paid=400_000, next_due=date(2026, 11, 1))
    db.session.add_all([
        PaymentInstallment(enrollment_id=enr.id, student_id=account.actor_id, seq=2,
                           amount=600_000, due_date=date(2026, 11, 1)),
        PaymentInstallment(enrollment_id=enr.id, student_id=account.actor_id, seq=1,
                           amount=400_000, due_date=date(2026, 10, 1), status="paid"),
    ])
    db.session.commit()

    body = client.get("/me/ledger", headers=headers).get_json()
    [row] = body["enrollments"]
    assert row["enrollment_id"] == enr.id
    assert row["course"] == {"id": course.id, "slug": course.slug,
                             "title": {"mn": course.title_mn, "en": "Leaders"}}
    assert row["cohort"]["name"] == "CL 2026-10"
    assert (row["total_due"], row["total_paid"], row["balance"]) == (1_000_000, 400_000, 600_000)
    assert row["next_due_date"] == "2026-11-01"
    assert [i["seq"] for i in row["installments"]] == [1, 2]
    assert row["installments"][0]["status"] == "paid"
    assert set(row["installments"][0]) == {"id", "seq", "due_date", "amount", "status", "paid_at"}


def test_ledger_without_ledger_row_reports_zeros(client, make_student, enroll):
    account, headers = make_student()
    enroll(account.actor_id)
    [row] = client.get("/me/ledger", headers=headers).get_json()["enrollments"]
    assert (row["total_due"], row["total_paid"], row["balance"]) == (0, 0, 0)
    assert row["next_due_date"] is None and row["installments"] == []


def test_ledger_hides_other_students(client, make_student, enroll, make_ledger):
    other, _ = make_student()
    make_ledger(enroll(other.actor_id))
    _, headers = make_student()
    assert client.get("/me/ledger", headers=headers).get_json() == {"enrollments": []}


# ----------------------------------------------------------------- invoices
def test_invoices_newest_first_without_qr(client, make_student, make_invoice):
    account, headers = make_student()
    old = make_invoice(account.actor_id)
    new = make_invoice(account.actor_id, status="paid")
    make_invoice(make_student()[0].actor_id)  # someone else's

    body = client.get("/me/invoices", headers=headers).get_json()
    assert [i["id"] for i in body["invoices"]] == [new.id, old.id]
    for inv in body["invoices"]:
        assert "qr_text" not in inv and "qr_image" not in inv and "provider_meta" not in inv


def test_invoices_filter_and_limit(client, make_student, make_invoice):
    account, headers = make_student()
    make_invoice(account.actor_id)
    paid = make_invoice(account.actor_id, status="paid")
    make_invoice(account.actor_id)

    body = client.get("/me/invoices?status=paid", headers=headers).get_json()
    assert [i["id"] for i in body["invoices"]] == [paid.id]
    assert len(client.get("/me/invoices?limit=2", headers=headers).get_json()["invoices"]) == 2


def test_invoices_bad_params_are_400(client, make_student):
    _, headers = make_student()
    resp = client.get("/me/invoices?status=bogus", headers=headers)
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_status"
    resp = client.get("/me/invoices?limit=abc", headers=headers)
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_limit"


# ----------------------------------------------------------------- receipts
def test_receipts_list_own_including_temp(client, make_student, make_invoice, make_receipt):
    account, headers = make_student()
    issued = make_receipt(make_invoice(account.actor_id, status="paid"))
    temp = make_receipt(make_invoice(account.actor_id, status="paid"), temp=True)
    linked = make_receipt(make_invoice(account.actor_id, status="paid"), via_payment=True)
    make_receipt(make_invoice(make_student()[0].actor_id, status="paid"))  # not theirs

    body = client.get("/me/receipts", headers=headers).get_json()
    by_id = {r["id"]: r for r in body["receipts"]}
    assert set(by_id) == {issued.id, temp.id, linked.id}
    assert by_id[temp.id]["is_temp_mode"] is True and by_id[temp.id]["status"] == "temp"
    assert by_id[issued.id]["ebarimt_id"] == issued.ebarimt_id
    assert by_id[issued.id]["lottery"] == "AB 12345678"
    for r in body["receipts"]:
        assert not {"raw", "pos_no", "emailed_to", "email_error"} & set(r)


def test_receipt_detail_and_ownership(client, make_student, make_invoice, make_receipt):
    account, headers = make_student()
    mine = make_receipt(make_invoice(account.actor_id, status="paid"))
    theirs = make_receipt(make_invoice(make_student()[0].actor_id, status="paid"))

    body = client.get(f"/me/receipts/{mine.id}", headers=headers).get_json()
    assert body["id"] == mine.id and body["qr_data"] == "QRDATA"
    assert body["issued_at"].endswith("+00:00")
    for rid in (theirs.id, 999999, "abc"):
        resp = client.get(f"/me/receipts/{rid}", headers=headers)
        assert resp.status_code == 404 and resp.get_json()["error"] == "receipt_not_found"
