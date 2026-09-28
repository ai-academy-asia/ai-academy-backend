"""Shared fixtures and helpers for the course write / S3 template tests."""
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
