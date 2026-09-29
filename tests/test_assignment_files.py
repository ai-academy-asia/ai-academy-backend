"""Student uploads: POST /me/files, download, and the 24 h cleanup (contract §2.8)."""
import io
from datetime import datetime, timedelta

import assignment_helpers
import pytest

from app.models import StudentFile
from app.services.assignments import files as files_svc
from app.services.assignments.cleanup import cleanup_unattached, files_cli

hw = assignment_helpers.hw
s3 = assignment_helpers.s3
make_assignment = assignment_helpers.make_assignment
make_file = assignment_helpers.make_file
make_submission = assignment_helpers.make_submission


def _upload(client, headers, name="report.pdf", data=b"%PDF-1.4 hello"):
    return client.post("/me/files", headers=headers, content_type="multipart/form-data",
                       data={"file": (io.BytesIO(data), name)})


# ----------------------------------------------------------------- upload
def test_upload_stores_privately_under_student_prefix(client, db, hw, s3):
    resp = _upload(client, hw.student_headers)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["file_name"] == "report.pdf"
    assert body["content_type"] == "application/pdf"
    assert body["size_bytes"] == len(b"%PDF-1.4 hello")
    key, content_type, data = s3.uploaded[0]
    assert key.startswith(f"students/{hw.sid}/") and key.endswith("_report.pdf")
    assert content_type == "application/pdf" and data == b"%PDF-1.4 hello"
    row = db.session.get(StudentFile, body["id"])
    assert row.student_id == hw.sid and row.file_key == key


def test_upload_keeps_cyrillic_name_with_safe_key(client, hw, s3):
    resp = _upload(client, hw.student_headers, name="Тайлан.docx")
    assert resp.status_code == 201
    assert resp.get_json()["file_name"] == "Тайлан.docx"
    assert s3.uploaded[0][0].endswith("_file.docx")


@pytest.mark.parametrize("name", ["virus.exe", "script.js", "noext", "page.html"])
def test_unsupported_type_is_400(client, hw, s3, name):
    resp = _upload(client, hw.student_headers, name=name)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "unsupported_file_type"
    assert s3.uploaded == []


def test_missing_or_empty_file_is_400(client, hw, s3):
    resp = client.post("/me/files", headers=hw.student_headers,
                       content_type="multipart/form-data", data={})
    assert resp.status_code == 400 and resp.get_json()["error"] == "file_required"
    resp = _upload(client, hw.student_headers, data=b"")
    assert resp.status_code == 400 and resp.get_json()["error"] == "file_required"


def test_too_large_is_413(client, hw, s3, monkeypatch):
    monkeypatch.setattr(files_svc, "MAX_FILE_BYTES", 10)
    resp = _upload(client, hw.student_headers, data=b"x" * 11)
    assert resp.status_code == 413
    assert resp.get_json()["error"] == "file_too_large"
    assert s3.uploaded == [] and StudentFile.query.count() == 0


def test_storage_failure_is_502_and_no_row(client, hw, s3):
    s3.fail = "upload"
    resp = _upload(client, hw.student_headers)
    assert resp.status_code == 502 and resp.get_json()["error"] == "storage_error"
    assert StudentFile.query.count() == 0


def test_upload_requires_student(client, hw, s3):
    assert _upload(client, {}).status_code == 401
    assert _upload(client, hw.teacher_headers).status_code == 403


# ----------------------------------------------------------------- download
def test_download_own_file(client, hw, s3, make_file):
    f = make_file(hw.sid, size_bytes=482133)
    resp = client.get(f"/me/files/{f.id}/download", headers=hw.student_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["url"] == f"https://s3.test/{f.file_key}?sig=1"
    assert body["file_name"] == "report.pdf" and body["size_bytes"] == 482133
    assert body["expires_at"].endswith("+00:00")


def test_download_someone_elses_file_is_404(client, hw, s3, make_file, make_student):
    f = make_file(make_student()[0].actor_id)
    for fid in (f.id, 999999):
        resp = client.get(f"/me/files/{fid}/download", headers=hw.student_headers)
        assert resp.status_code == 404 and resp.get_json()["error"] == "file_not_found"
    assert s3.signed == []


def test_download_presign_failure_is_503(client, hw, s3, make_file):
    s3.fail = "presign"
    f = make_file(hw.sid)
    resp = client.get(f"/me/files/{f.id}/download", headers=hw.student_headers)
    assert resp.status_code == 503 and resp.get_json()["error"] == "storage_error"


def test_download_requires_student(client, hw, make_file):
    f = make_file(hw.sid)
    assert client.get(f"/me/files/{f.id}/download").status_code == 401
    assert client.get(f"/me/files/{f.id}/download",
                      headers=hw.teacher_headers).status_code == 403


# ----------------------------------------------------------------- cleanup
def test_cleanup_drops_only_stale_unattached_files(app, db, hw, s3, make_file,
                                                   make_assignment, make_submission):
    old = datetime.utcnow() - timedelta(hours=25)
    stale = make_file(hw.sid, name="stale.pdf", created_at=old)
    attached = make_file(hw.sid, name="attached.pdf", created_at=old)
    fresh = make_file(hw.sid, name="fresh.pdf")
    make_submission(make_assignment(hw.cohort), hw.sid, file_id=attached.id)
    stale_key = stale.file_key

    assert cleanup_unattached() == {"deleted": 1, "failed": 0}
    assert s3.deleted == [stale_key]
    remaining = {f.file_name for f in StudentFile.query.all()}
    assert remaining == {attached.file_name, fresh.file_name}


def test_cleanup_keeps_row_when_s3_delete_fails(app, db, hw, s3, make_file):
    make_file(hw.sid, created_at=datetime.utcnow() - timedelta(days=2))
    s3.fail = "delete"
    assert cleanup_unattached() == {"deleted": 0, "failed": 1}
    assert StudentFile.query.count() == 1


def test_cleanup_cli(app, db, hw, s3, make_file):
    make_file(hw.sid, created_at=datetime.utcnow() - timedelta(days=2))
    result = app.test_cli_runner().invoke(files_cli, ["cleanup"])
    assert result.exit_code == 0
    assert "1 deleted, 0 failed" in result.output
