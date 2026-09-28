"""Course S3 template download and delete (GET/DELETE /courses/<ref>/templates/<kind>)."""


import admin_course_helpers
from admin_course_helpers import _fresh, _upload

from app.models import Course

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
editor = admin_course_helpers.editor
s3 = admin_course_helpers.s3


# ---------------------------------------------------------------- templates: download
def test_download_template(client, editor, make_course, s3):
    cid = make_course().id
    _upload(client, editor, cid, "contract", "Гэрээ.docx", b"DOCX-BYTES",
            content_type="application/vnd.openxmlformats-officedocument."
                         "wordprocessingml.document")
    resp = client.get(f"/courses/{cid}/templates/contract", headers=editor)
    assert resp.status_code == 200
    assert resp.data == b"DOCX-BYTES"
    assert resp.mimetype.endswith("wordprocessingml.document")
    disposition = resp.headers["Content-Disposition"]
    assert disposition.startswith("attachment")
    assert "filename*=UTF-8''%D0%93%D1%8D%D1%80%D1%8D%D1%8D.docx" in disposition


def test_download_guesses_mimetype_when_s3_has_none(client, editor, make_course, db, s3):
    cid = make_course().id
    course = db.session.get(Course, cid)
    course.cert_template_key = f"courses/{cid}/cert_template.pdf"
    course.cert_template_name = None
    db.session.commit()
    s3.objects[f"courses/{cid}/cert_template.pdf"] = (b"%PDF", None)

    resp = client.get(f"/courses/{cid}/templates/cert", headers=editor)
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert "cert_template.pdf" in resp.headers["Content-Disposition"]


def test_download_missing_template_is_404(client, editor, make_course, s3):
    cid = make_course().id
    resp = client.get(f"/courses/{cid}/templates/cert", headers=editor)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_download_bad_kind_is_400(client, editor, make_course, s3):
    cid = make_course().id
    resp = client.get(f"/courses/{cid}/templates/photo", headers=editor)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_kind"


def test_download_storage_failure_is_502(client, editor, make_course, s3):
    cid = make_course().id
    _upload(client, editor, cid)
    s3.fail.add("download")
    resp = client.get(f"/courses/{cid}/templates/cert", headers=editor)
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "storage_error"


def test_download_unknown_course_is_404(client, editor, s3):
    resp = client.get("/courses/9999/templates/cert", headers=editor)
    assert resp.status_code == 404


# ---------------------------------------------------------------- templates: delete
def test_delete_template(client, editor, make_course, db, s3):
    cid = make_course().id
    _upload(client, editor, cid, "cert")
    _upload(client, editor, cid, "contract", "c.docx")
    resp = client.delete(f"/courses/{cid}/templates/cert", headers=editor)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "deleted"}
    assert list(s3.objects) == [f"courses/{cid}/contract_template.docx"]
    course = _fresh(db, cid)
    assert course.cert_template_key is None and course.cert_template_name is None
    assert course.contract_template_key is not None


def test_delete_absent_template_is_a_no_op(client, editor, make_course, s3):
    cid = make_course().id
    resp = client.delete(f"/courses/{cid}/templates/contract", headers=editor)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "deleted"}


def test_delete_template_bad_kind_is_400(client, editor, make_course, s3):
    cid = make_course().id
    resp = client.delete(f"/courses/{cid}/templates/other", headers=editor)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_kind"


def test_delete_template_storage_failure_keeps_reference(client, editor, make_course, db, s3):
    cid = make_course().id
    _upload(client, editor, cid)
    s3.fail.add("delete")
    resp = client.delete(f"/courses/{cid}/templates/cert", headers=editor)
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "storage_error"
    assert _fresh(db, cid).cert_template_key is not None


def test_delete_template_unknown_course_is_404(client, editor, s3):
    resp = client.delete("/courses/nope/templates/cert", headers=editor)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"
