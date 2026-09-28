"""Finance back office: auth matrix, raising and reading invoices."""
import payments_helpers
import pytest
from payments_helpers import _create

from app.payments import PaymentGatewayError

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
enroll = payments_helpers.enroll
finance = payments_helpers.finance
installment = payments_helpers.installment


# ================================================================ auth matrix
ENDPOINTS = [
    ("post", "/admin/invoices"),
    ("get", "/admin/invoices"),
    ("get", "/admin/invoices/1"),
    ("post", "/admin/invoices/1/check"),
    ("get", "/admin/payments"),
    ("post", "/admin/payments/reconcile/golomt"),
    ("get", "/admin/ledger/1"),
    ("post", "/admin/ledger/1/recompute"),
]


@pytest.mark.parametrize("method, url", ENDPOINTS)
def test_requires_token(client, method, url):
    resp = getattr(client, method)(url, json={})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


@pytest.mark.parametrize("method, url", ENDPOINTS)
@pytest.mark.parametrize("role", ["sales_enrollment", "content_marketing"])
def test_non_finance_staff_forbidden(client, make_staff, method, url, role):
    resp = getattr(client, method)(url, json={}, headers=make_staff(role)[1])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


@pytest.mark.parametrize("method, url", ENDPOINTS)
def test_students_forbidden(client, make_student, method, url):
    resp = getattr(client, method)(url, json={}, headers=make_student()[1])
    assert resp.status_code == 403


# ============================================================ POST /admin/invoices
def test_finance_creates_invoice_for_enrollment(client, gateways, finance, enroll):
    enr = enroll()
    resp = _create(client, finance, enrollment_id=enr.id, description="Term 1")
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "pending"
    assert data["enrollment_id"] == enr.id
    assert data["student_id"] == enr.student_id  # derived from the enrollment
    assert data["amount"] == 300000.0
    assert gateways["qpay"].created[0].customer["name"] == "Bat"


def test_super_admin_creates_invoice(client, gateways, admin_headers):
    assert _create(client, admin_headers).status_code == 201


def test_create_invoice_derives_links_from_installment(client, gateways, finance, enroll,
                                                       installment):
    enr = enroll()
    inst = installment(enr)
    data = _create(client, finance, installment_id=inst.id).get_json()
    assert data["installment_id"] == inst.id
    assert data["enrollment_id"] == enr.id
    assert data["student_id"] == enr.student_id


def test_create_invoice_uses_explicit_customer(client, gateways, finance, enroll):
    customer = {"name": "ACME LLC", "register": "1234567"}
    resp = _create(client, finance, enrollment_id=enroll().id, customer=customer)
    assert resp.status_code == 201
    assert gateways["qpay"].created[0].customer == customer


def test_golomt_invoice_carries_course_hint(client, gateways, finance, enroll, db):
    from app.models import Course

    enr = enroll()
    course = db.session.get(Course, enr.course_id)
    resp = _create(client, finance, provider="golomt", enrollment_id=enr.id)
    assert resp.status_code == 201
    assert resp.get_json()["sender_invoice_no"].startswith("AIAA-GO-")
    assert gateways["golomt"].created[0].extra == {
        "course_slug": course.slug, "course_title": course.title_mn,
    }


@pytest.mark.parametrize("fields, status, code", [
    ({"provider": "paypal"}, 400, "unsupported_provider"),
    ({"provider": None}, 400, "unsupported_provider"),
    ({"amount": "x"}, 400, "invalid_amount"),
    ({"amount": 0}, 400, "amount_must_be_positive"),
    ({"enrollment_id": 9999}, 404, "enrollment_not_found"),
    ({"student_id": 9999}, 404, "student_not_found"),
    ({"installment_id": 9999}, 404, "installment_not_found"),
])
def test_create_invoice_validation(client, db, gateways, finance, fields, status, code):
    from app.models import Invoice

    resp = _create(client, finance, **fields)
    assert resp.status_code == status
    assert resp.get_json()["error"] == code
    assert Invoice.query.count() == 0


def test_create_invoice_sandbox_refused_when_disabled(client, db, finance):
    # Uses the real registry: the service accepts the name, get_provider refuses it.
    resp = _create(client, finance, provider="sandbox")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "gateway_unsupported_provider"


def test_create_invoice_gateway_failure(client, db, gateways, finance):
    from app.models import Invoice

    gateways["qpay"].fail = PaymentGatewayError("qpay", "gateway_http_500",
                                                detail={"message": "down"})
    resp = _create(client, finance)
    assert resp.status_code == 502
    assert resp.get_json() == {"error": "gateway_gateway_http_500", "provider": "qpay",
                               "detail": {"message": "down"}}
    assert Invoice.query.count() == 0


# ============================================================= GET /admin/invoices
def test_list_invoices_with_filters(client, gateways, finance, enroll):
    enr = enroll()
    a = _create(client, finance, enrollment_id=enr.id).get_json()
    b = _create(client, finance, provider="storepay").get_json()
    c = _create(client, finance, provider="golomt", student_id=enr.student_id).get_json()
    gateways["qpay"].paid = True
    client.post(f"/admin/invoices/{a['id']}/check", headers=finance)

    def ids(query=""):
        resp = client.get(f"/admin/invoices{query}", headers=finance)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == len(data["invoices"])
        return [i["id"] for i in data["invoices"]]

    assert ids() == [c["id"], b["id"], a["id"]]  # newest first
    assert ids("?provider=storepay") == [b["id"]]
    assert ids("?status=paid") == [a["id"]]
    assert ids("?status=pending") == [c["id"], b["id"]]
    assert ids(f"?enrollment_id={enr.id}") == [a["id"]]
    assert ids(f"?student_id={enr.student_id}") == [c["id"], a["id"]]
    assert ids("?student_id=abc") == [c["id"], b["id"], a["id"]]  # non-numeric ignored
    assert ids("?limit=1") == [c["id"]]

    listed = client.get("/admin/invoices", headers=finance).get_json()["invoices"][0]
    assert "qr_text" not in listed


def test_list_invoices_rejects_non_numeric_limit(client, finance):
    resp = client.get("/admin/invoices?limit=abc", headers=finance)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_limit"


@pytest.mark.parametrize("path", ["/admin/payments", "/admin/ebarimt"])
def test_other_listings_reject_non_numeric_limit(client, finance, path):
    resp = client.get(f"{path}?limit=abc", headers=finance)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_limit"


# ======================================================= GET /admin/invoices/<id>
def test_get_invoice(client, gateways, finance):
    inv = _create(client, finance).get_json()
    resp = client.get(f"/admin/invoices/{inv['id']}", headers=finance)
    assert resp.status_code == 200
    assert resp.get_json()["sender_invoice_no"] == inv["sender_invoice_no"]
    assert resp.get_json()["qr_text"] == inv["qr_text"]


def test_get_invoice_not_found(client, finance):
    resp = client.get("/admin/invoices/9999", headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "invoice_not_found"
