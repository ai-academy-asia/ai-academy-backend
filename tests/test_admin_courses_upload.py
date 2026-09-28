"""Course S3 template upload (PUT /courses/<ref>/templates/<kind>)."""

import admin_course_helpers
import pytest
from admin_course_helpers import _fresh, _upload

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
editor = admin_course_helpers.editor
s3 = admin_course_helpers.s3


# ---------------------------------------------------------------- templates: upload
@pytest.mark.parametrize("kind,filename", [("cert", "Cert.PDF"), ("contract", "gereee.docx"),
                                           ("contract", "old.doc")])
def test_upload_template(client, editor, make_course, db, s3, kind, filename):
    cid = make_course().id
    resp = _upload(client, editor, cid, kind, filename, b"payload",
                   content_type="application/octet-stream")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "kind": kind, "filename": filename}
    ext = filename.rsplit(".", 1)[1].lower()
    key = f"courses/{cid}/{kind}_template.{ext}"
    assert s3.objects[key] == (b"payload", "application/octet-stream")
    course = _fresh(db, cid)
    assert getattr(course, f"{kind}_template_key") == key
    assert getattr(course, f"{kind}_template_name") == filename

    detail = client.patch(f"/courses/{cid}", headers=editor, json={}).get_json()
    assert detail[f"has_{kind}_template"] is True
    assert detail[f"{kind}_template_name"] == filename


def test_upload_by_slug_uses_course_id_in_key(client, editor, make_course, s3):
    cid = make_course(slug="ai-101").id
    assert _upload(client, editor, "ai-101").status_code == 200
    assert list(s3.objects) == [f"courses/{cid}/cert_template.pdf"]


def test_upload_replaces_same_kind(client, editor, make_course, db, s3):
    cid = make_course().id
    _upload(client, editor, cid, data=b"v1")
    _upload(client, editor, cid, data=b"v2", filename="v2.pdf")
    assert s3.objects[f"courses/{cid}/cert_template.pdf"][0] == b"v2"
    assert _fresh(db, cid).cert_template_name == "v2.pdf"


def test_upload_with_new_extension_drops_old_object(client, editor, make_course, s3):
    cid = make_course().id
    _upload(client, editor, cid, "contract", "c.pdf")
    _upload(client, editor, cid, "contract", "c.docx")
    assert list(s3.objects) == [f"courses/{cid}/contract_template.docx"]


def test_reupload_survives_failing_to_delete_the_old_object(client, editor, make_course, s3):
    cid = make_course().id
    _upload(client, editor, cid, "contract", "c.pdf")
    s3.fail.add("delete")
    resp = _upload(client, editor, cid, "contract", "c.docx")
    assert resp.status_code == 200
    assert f"courses/{cid}/contract_template.docx" in s3.objects


def test_upload_bad_kind_is_400(client, editor, make_course, s3):
    cid = make_course().id
    resp = _upload(client, editor, cid, kind="diploma")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_kind"
    assert s3.objects == {}


def test_upload_without_file_is_400(client, editor, make_course, s3):
    cid = make_course().id
    resp = client.put(f"/courses/{cid}/templates/cert", headers=editor,
                      data={"other": "x"}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "file_required"


def test_upload_empty_filename_is_400(client, editor, make_course, s3):
    cid = make_course().id
    resp = _upload(client, editor, cid, filename="")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "file_required"


@pytest.mark.parametrize("filename", ["cert.png", "cert", "cert.pdf.exe"])
def test_upload_bad_extension_is_400(client, editor, make_course, db, s3, filename):
    cid = make_course().id
    resp = _upload(client, editor, cid, filename=filename)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "unsupported_file_type"
    assert body["allowed"] == [".doc", ".docx", ".pdf"]
    assert s3.objects == {}
    assert _fresh(db, cid).cert_template_key is None


def test_upload_too_large_is_413(client, app, editor, make_course, s3, monkeypatch):
    monkeypatch.setitem(app.config, "MAX_TEMPLATE_BYTES", 100)
    cid = make_course().id
    resp = _upload(client, editor, cid, data=b"x" * 500)
    assert resp.status_code == 413
    assert resp.get_json() == {"error": "file_too_large", "max_bytes": 100}
    assert s3.objects == {}


def test_upload_storage_failure_is_502(client, editor, make_course, db, s3):
    cid = make_course().id
    s3.fail.add("upload")
    resp = _upload(client, editor, cid)
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "storage_error"
    assert _fresh(db, cid).cert_template_key is None


def test_upload_unknown_course_is_404(client, editor, s3):
    resp = _upload(client, editor, "nope")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"
