"""Course writes (POST/PATCH/DELETE /courses) and S3 template files."""
import io

import pytest

from app.models import Course
from app.storage import S3StorageError


def _fresh(db, pk):
    db.session.expire_all()
    return db.session.get(Course, pk)


class FakeS3:
    """In-memory stand-in for the app.storage functions the course service imports."""

    def __init__(self):
        self.objects = {}
        self.fail = set()  # operation names that raise S3StorageError

    def _check(self, op):
        if op in self.fail:
            raise S3StorageError(f"{op} failed")

    def upload_fileobj(self, fileobj, key, content_type=None):
        self._check("upload")
        self.objects[key] = (fileobj.read(), content_type)

    def download_stream(self, key):
        self._check("download")
        if key not in self.objects:
            raise S3StorageError("NoSuchKey")
        data, content_type = self.objects[key]
        return io.BytesIO(data), content_type

    def delete_object(self, key):
        self._check("delete")
        self.objects.pop(key, None)


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    for name in ("upload_fileobj", "download_stream", "delete_object"):
        monkeypatch.setattr(f"app.services.courses.{name}", getattr(fake, name))
    return fake


@pytest.fixture
def editor(make_staff):
    return make_staff("content_marketing")[1]


def _upload(client, headers, ref, kind="cert", filename="cert.pdf", data=b"%PDF-1.4 cert",
            content_type=None):
    file = (io.BytesIO(data), filename, content_type) if content_type else \
        (io.BytesIO(data), filename)
    return client.put(f"/courses/{ref}/templates/{kind}", headers=headers,
                      data={"file": file}, content_type="multipart/form-data")


# ---------------------------------------------------------------- auth
@pytest.mark.parametrize("method,path", [
    ("post", "/courses"), ("patch", "/courses/1"), ("delete", "/courses/1"),
    ("put", "/courses/1/templates/cert"), ("get", "/courses/1/templates/cert"),
    ("delete", "/courses/1/templates/cert"),
])
def test_requires_token(client, method, path):
    resp = getattr(client, method)(path, json={})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


@pytest.mark.parametrize("role", ["sales_enrollment", "finance"])
def test_forbidden_without_course_edit(client, make_staff, make_course, s3, role):
    course = make_course()
    _, headers = make_staff(role)
    for method, path in [
        ("post", "/courses"), ("patch", f"/courses/{course.id}"),
        ("delete", f"/courses/{course.id}"),
        ("put", f"/courses/{course.id}/templates/cert"),
        ("get", f"/courses/{course.id}/templates/cert"),
        ("delete", f"/courses/{course.id}/templates/cert"),
    ]:
        resp = getattr(client, method)(path, json={"slug": "x", "title_mn": "x"},
                                       headers=headers)
        assert resp.status_code == 403, (method, path)
        assert resp.get_json()["error"] == "forbidden"
    assert Course.query.count() == 1


def test_students_are_forbidden(client, make_student):
    _, headers = make_student()
    resp = client.post("/courses", headers=headers, json={"slug": "x", "title_mn": "x"})
    assert resp.status_code == 403


# ---------------------------------------------------------------- create
def test_create_course_defaults_to_draft(client, editor, db):
    resp = client.post("/courses", headers=editor, json={
        "slug": "corporate-leaders", "title_mn": "Корпорат удирдагчид", "title_en": "Leaders",
        "level": "adult", "price_amount": 2500000, "discount_percent": 10,
        "start_date": "2026-08-06", "curriculum": [{"week": 1, "topic": "AI"}],
        "cert_template_key": "hijack", "id": 999,
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "draft"
    assert body["slug"] == "corporate-leaders"
    assert body["title"] == {"mn": "Корпорат удирдагчид", "en": "Leaders"}
    assert body["start_date"] == "2026-08-06"
    assert body["final_price_amount"] == 2250000.0
    assert body["has_cert_template"] is False
    assert body["id"] != 999
    course = db.session.get(Course, body["id"])
    assert course.cert_template_key is None
    assert course.curriculum == [{"week": 1, "topic": "AI"}]


@pytest.mark.parametrize("fields,error", [
    ({"slug": ""}, "slug_required"),
    ({"title_mn": None}, "title_mn_required"),
    ({"status": "archived"}, "invalid_status"),
    ({"level": "senior"}, "invalid_level"),
])
def test_create_validation(client, admin_headers, fields, error):
    data = {"slug": "c", "title_mn": "C"}
    data.update(fields)
    resp = client.post("/courses", headers=admin_headers, json=data)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    assert Course.query.count() == 0


def test_create_invalid_date_names_field(client, admin_headers):
    resp = client.post("/courses", headers=admin_headers,
                       json={"slug": "c", "title_mn": "C", "end_date": "soon"})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "invalid_date", "field": "end_date"}


def test_create_duplicate_slug_is_409(client, admin_headers, make_course):
    make_course(slug="taken")
    resp = client.post("/courses", headers=admin_headers, json={"slug": "taken", "title_mn": "X"})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "slug_taken"
    assert Course.query.count() == 1


# ---------------------------------------------------------------- update
@pytest.mark.parametrize("by", ["id", "slug"])
def test_update_by_id_or_slug(client, editor, make_course, db, by):
    course = make_course(slug="ai-basics", status="draft")
    cid = course.id
    ref = cid if by == "id" else "ai-basics"
    resp = client.patch(f"/courses/{ref}", headers=editor, json={
        "status": "open", "tagline_mn": "Шинэ", "start_date": "2026-09-01",
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "open"
    assert body["tagline"]["mn"] == "Шинэ"
    assert body["start_date"] == "2026-09-01"
    assert _fresh(db, cid).status == "open"


def test_update_can_clear_date(client, editor, make_course, db):
    from datetime import date

    cid = make_course(start_date=date(2026, 9, 1)).id
    resp = client.patch(f"/courses/{cid}", headers=editor, json={"start_date": ""})
    assert resp.status_code == 200
    assert _fresh(db, cid).start_date is None


@pytest.mark.parametrize("fields,error", [
    ({"slug": ""}, "slug_required"),
    ({"title_mn": ""}, "title_mn_required"),
    ({"status": "gone"}, "invalid_status"),
    ({"level": "phd"}, "invalid_level"),
    ({"start_date": "2026-02-30"}, "invalid_date"),
])
def test_update_validation(client, editor, make_course, db, fields, error):
    cid = make_course(slug="keep", status="open").id
    resp = client.patch(f"/courses/{cid}", headers=editor, json=fields)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    db.session.rollback()  # requests share the fixture's app context; mimic teardown
    course = _fresh(db, cid)
    assert course.slug == "keep" and course.status == "open"


def test_update_to_taken_slug_is_409(client, editor, make_course, db):
    make_course(slug="taken")
    cid = make_course(slug="mine").id
    resp = client.patch(f"/courses/{cid}", headers=editor, json={"slug": "taken"})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "slug_taken"
    assert _fresh(db, cid).slug == "mine"


@pytest.mark.parametrize("ref", ["9999", "no-such-course"])
def test_update_unknown_is_404(client, editor, ref):
    resp = client.patch(f"/courses/{ref}", headers=editor, json={"title_mn": "X"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------- delete
@pytest.mark.parametrize("by", ["id", "slug"])
def test_delete_course(client, editor, make_course, db, s3, by):
    course = make_course(slug="gone")
    cid = course.id
    resp = client.delete(f"/courses/{cid if by == 'id' else 'gone'}", headers=editor)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "deleted"}
    assert _fresh(db, cid) is None


def test_delete_course_removes_its_templates(client, editor, make_course, db, s3):
    cid = make_course().id
    _upload(client, editor, cid, "cert", "cert.pdf")
    _upload(client, editor, cid, "contract", "contract.docx")
    assert len(s3.objects) == 2
    assert client.delete(f"/courses/{cid}", headers=editor).status_code == 200
    assert s3.objects == {}


def test_delete_course_survives_s3_cleanup_failure(client, editor, make_course, db, s3):
    cid = make_course().id
    _upload(client, editor, cid)
    s3.fail.add("delete")
    assert client.delete(f"/courses/{cid}", headers=editor).status_code == 200
    assert _fresh(db, cid) is None


def test_delete_course_in_use_is_409(client, editor, make_course, make_cohort, db, s3):
    course = make_course()
    cid = course.id
    make_cohort(course=course)
    _upload(client, editor, cid)
    resp = client.delete(f"/courses/{cid}", headers=editor)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "course_in_use"
    assert _fresh(db, cid) is not None
    assert len(s3.objects) == 1  # templates kept with the course


def test_delete_unknown_is_404(client, editor):
    resp = client.delete("/courses/9999", headers=editor)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


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


@pytest.mark.xfail(strict=True, reason="re-uploading a template with a different extension "
                   "writes a new key and orphans the old S3 object")
def test_upload_with_new_extension_drops_old_object(client, editor, make_course, s3):
    cid = make_course().id
    _upload(client, editor, cid, "contract", "c.pdf")
    _upload(client, editor, cid, "contract", "c.docx")
    assert list(s3.objects) == [f"courses/{cid}/contract_template.docx"]


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
