"""Staff issuing (/admin/certificates), files, student download and public verify."""
import io

import account_helpers
from account_helpers import _rows

enroll = account_helpers.enroll
make_ledger = account_helpers.make_ledger
make_lessons = account_helpers.make_lessons
complete = account_helpers.complete
earned = account_helpers.earned
s3 = account_helpers.s3


def _issue(client, headers, **payload):
    return client.post("/admin/certificates", headers=headers, json=payload)


def _upload(client, headers, cert_id, filename="c.pdf", data=b"%PDF-1.4"):
    return client.put(f"/admin/certificates/{cert_id}/file", headers=headers,
                      data={"file": (io.BytesIO(data), filename)},
                      content_type="multipart/form-data")


# ----------------------------------------------------------------- issue
def test_issue_eligible_student(client, db, earned, admin_headers):
    from app.models import Certificate

    account, _, course, enr = earned
    resp = _issue(client, admin_headers, student_id=account.actor_id, course_id=course.id)
    assert resp.status_code == 201
    body = resp.get_json()
    year = body["issued_at"][:4]
    assert body["cert_number"] == f"AIAA-{year}-00001"
    assert body["verify_url"] == f"http://testserver/certificates/verify/AIAA-{year}-00001"
    assert body["payment_cleared"] is True and body["enrollment_id"] == enr.id
    assert body["student_name"] == "Bat Dorj" and body["course_title"]["en"] == "Leaders"
    [row] = _rows(db, Certificate)
    assert row.is_archived is False


def test_numbers_increase(client, make_student, make_course, make_cohort, enroll, make_lessons,
                          complete, admin_headers):
    numbers = []
    for _ in range(2):
        account, _ = make_student()
        course = make_course(price_amount=0)
        complete(enroll(account.actor_id, make_cohort(course=course)), make_lessons(course, 1))
        numbers.append(_issue(client, admin_headers, student_id=account.actor_id,
                              course_id=course.id).get_json()["cert_number"])
    assert [n[-5:] for n in numbers] == ["00001", "00002"]


def test_not_eligible_is_409_unless_forced(client, make_student, make_course, make_cohort, enroll,
                                           admin_headers):
    account, _ = make_student()
    course = make_course()
    enroll(account.actor_id, make_cohort(course=course))
    resp = _issue(client, admin_headers, student_id=account.actor_id, course_id=course.id)
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["error"] == "not_eligible" and body["enrolled"] is True
    assert body["requirements"]["payment_cleared"] == {"done": False}

    resp = _issue(client, admin_headers, student_id=account.actor_id, course_id=course.id,
                  force=True)
    assert resp.status_code == 201 and resp.get_json()["payment_cleared"] is False


def test_not_enrolled_needs_force(client, make_student, make_course, admin_headers):
    account, _ = make_student()
    course = make_course(price_amount=0)
    resp = _issue(client, admin_headers, student_id=account.actor_id, course_id=course.id)
    assert resp.status_code == 409 and resp.get_json()["enrolled"] is False
    resp = _issue(client, admin_headers, student_id=account.actor_id, course_id=course.id,
                  force=True)
    assert resp.status_code == 201 and resp.get_json()["enrollment_id"] is None


def test_duplicate_is_already_issued(client, earned, admin_headers):
    account, _, course, _ = earned
    payload = {"student_id": account.actor_id, "course_id": course.id}
    first = _issue(client, admin_headers, **payload).get_json()
    client.delete(f"/admin/certificates/{first['id']}", headers=admin_headers)
    resp = _issue(client, admin_headers, force=True, **payload)
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "already_issued", "certificate_id": first["id"],
                               "archived": True}


def test_issue_validation(client, make_student, make_course, admin_headers):
    resp = _issue(client, admin_headers, course_id=1)
    assert resp.status_code == 400 and resp.get_json()["error"] == "student_id_required"
    resp = _issue(client, admin_headers, student_id=1)
    assert resp.status_code == 400 and resp.get_json()["error"] == "course_id_required"
    resp = _issue(client, admin_headers, student_id="abc", course_id=make_course().id)
    assert resp.status_code == 404 and resp.get_json()["error"] == "student_not_found"
    resp = _issue(client, admin_headers, student_id=make_student()[0].actor_id, course_id=999)
    assert resp.status_code == 404 and resp.get_json()["error"] == "course_not_found"


def test_staff_permissions(client, make_staff, make_student, make_teacher):
    manager = make_staff("sales_enrollment")[1]
    for headers, code in (({}, 401), (make_student()[1], 403), (make_teacher()[1], 403),
                          (make_staff("content_marketing")[1], 403)):
        assert client.get("/admin/certificates", headers=headers).status_code == code
        assert _issue(client, headers, student_id=1, course_id=1).status_code == code
        assert client.delete("/admin/certificates/1", headers=headers).status_code == code
    assert client.get("/admin/certificates", headers=manager).status_code == 200


# ----------------------------------------------------------------- list / archive
def test_list_filters(client, earned, make_student, make_course, admin_headers):
    account, _, course, _ = earned
    other = make_student()[0]
    other_course = make_course()
    for sid, cid in ((account.actor_id, course.id), (other.actor_id, course.id),
                     (account.actor_id, other_course.id)):
        _issue(client, admin_headers, student_id=sid, course_id=cid, force=True)
    get = lambda q: client.get(f"/admin/certificates{q}", headers=admin_headers).get_json()  # noqa: E731
    assert len(get("")["certificates"]) == 3
    assert len(get(f"?course_id={course.id}")["certificates"]) == 2
    assert len(get(f"?student_id={other.actor_id}")["certificates"]) == 1
    assert len(get("?limit=1")["certificates"]) == 1
    assert get("?course_id=abc")["certificates"] == []


def test_archive_hides_from_student_and_verify(client, earned, admin_headers, s3):
    account, headers, course, _ = earned
    cert = _issue(client, admin_headers, student_id=account.actor_id,
                  course_id=course.id).get_json()
    _upload(client, admin_headers, cert["id"])
    resp = client.delete(f"/admin/certificates/{cert['id']}", headers=admin_headers)
    assert resp.status_code == 200 and resp.get_json()["is_archived"] is True

    status = client.get(f"/me/courses/{course.slug}/certificate", headers=headers).get_json()
    assert status["status"] == "eligible" and status["certificate"] is None
    assert client.get(f"/certificates/verify/{cert['cert_number']}").status_code == 404
    resp = client.get(f"/me/certificates/{cert['cert_number']}/download", headers=headers)
    assert resp.get_json()["error"] == "certificate_not_found"
    assert client.delete("/admin/certificates/999", headers=admin_headers).status_code == 404


# ----------------------------------------------------------------- files + download
def test_upload_and_download(client, earned, make_student, admin_headers, s3):
    account, headers, course, _ = earned
    cert = _issue(client, admin_headers, student_id=account.actor_id,
                  course_id=course.id).get_json()
    number = cert["cert_number"]
    resp = client.get(f"/me/certificates/{number}/download", headers=headers)
    assert resp.status_code == 404 and resp.get_json()["error"] == "certificate_file_missing"

    resp = _upload(client, admin_headers, cert["id"], "Cert.PDF")
    assert resp.status_code == 200 and resp.get_json()["has_file"] is True
    assert s3.objects[f"certificates/{number}.pdf"] == (b"%PDF-1.4", "application/pdf")

    body = client.get(f"/me/certificates/{number}/download", headers=headers).get_json()
    assert body["url"] == f"https://s3.test/certificates/{number}.pdf?expires=300"
    assert body["expires_at"].endswith("+00:00")

    stranger = client.get(f"/me/certificates/{number}/download", headers=make_student()[1])
    assert stranger.status_code == 404
    s3.fail.add("presign")
    resp = client.get(f"/me/certificates/{number}/download", headers=headers)
    assert resp.status_code == 502 and resp.get_json()["error"] == "storage_error"



def test_upload_validation(client, earned, admin_headers, s3, app, monkeypatch):
    account, _, course, _ = earned
    cert = _issue(client, admin_headers, student_id=account.actor_id,
                  course_id=course.id).get_json()
    resp = _upload(client, admin_headers, cert["id"], "c.docx")
    assert resp.status_code == 400 and resp.get_json()["error"] == "unsupported_file_type"
    resp = client.put(f"/admin/certificates/{cert['id']}/file", headers=admin_headers,
                      data={}, content_type="multipart/form-data")
    assert resp.status_code == 400 and resp.get_json()["error"] == "file_required"
    monkeypatch.setitem(app.config, "MAX_CERTIFICATE_BYTES", 10)
    resp = _upload(client, admin_headers, cert["id"], data=b"x" * 100)
    assert resp.status_code == 413 and resp.get_json()["error"] == "file_too_large"
    monkeypatch.setitem(app.config, "MAX_CERTIFICATE_BYTES", None)
    s3.fail.add("upload")
    resp = _upload(client, admin_headers, cert["id"])
    assert resp.status_code == 502 and resp.get_json()["error"] == "storage_error"
    assert s3.objects == {}
    assert _upload(client, admin_headers, 999).status_code == 404


# ----------------------------------------------------------------- public verify
def test_verify_public(client, earned, admin_headers):
    account, _, course, _ = earned
    cert = _issue(client, admin_headers, student_id=account.actor_id,
                  course_id=course.id).get_json()
    resp = client.get(f"/certificates/verify/{cert['cert_number']}")
    assert resp.status_code == 200
    assert resp.get_json() == {
        "valid": True, "cert_number": cert["cert_number"], "student_name": "Bat Dorj",
        "course_title": {"mn": course.title_mn, "en": "Leaders"},
        "issued_at": cert["issued_at"],
    }
    resp = client.get("/certificates/verify/AIAA-2026-99999")
    assert resp.status_code == 404 and resp.get_json()["error"] == "certificate_not_found"
