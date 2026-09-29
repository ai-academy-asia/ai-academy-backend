"""PUT /me/lessons/<id>/note and GET /me/materials/<id>/download (contract §2.4, §2.5)."""
import learning_helpers as h
import pytest

from app.models import LessonNote

world = h.world
s3 = h.s3


@pytest.fixture
def lesson(db, world):
    return h.lesson(db, h.module(db, world.course))


# ---------------------------------------------------------------- notes
def test_note_create_then_update(client, db, world, lesson):
    url = f"/me/lessons/{lesson.id}/note"
    resp = client.put(url, headers=world.headers, json={"content": "  анхны тэмдэглэл  "})
    assert resp.status_code == 201
    note = resp.get_json()
    assert note["content"] == "анхны тэмдэглэл"
    assert note["author"] == {"name": "Болд Батаа", "initials": "ББ"}
    assert note["created_at"].endswith("+00:00") and note["updated_at"]

    resp = client.put(url, headers=world.headers, json={"content": "шинэ"})
    assert resp.status_code == 200
    assert resp.get_json()["id"] == note["id"]
    assert resp.get_json()["content"] == "шинэ"
    assert LessonNote.query.count() == 1

    detail = client.get(f"/me/lessons/{lesson.id}", headers=world.headers).get_json()
    assert detail["note"]["id"] == note["id"]
    assert detail["note"]["content"] == "шинэ"


@pytest.mark.parametrize("payload", [{}, {"content": "   "}, {"content": 5}, None])
def test_note_content_required(client, world, lesson, payload):
    resp = client.put(f"/me/lessons/{lesson.id}/note", headers=world.headers, json=payload)
    assert (resp.status_code, resp.get_json()["error"]) == (400, "content_required")


def test_note_too_long(client, world, lesson):
    url = f"/me/lessons/{lesson.id}/note"
    resp = client.put(url, headers=world.headers, json={"content": "x" * 5001})
    assert (resp.status_code, resp.get_json()["error"]) == (400, "content_too_long")
    assert client.put(url, headers=world.headers, json={"content": "x" * 5000}).status_code == 201


def test_notes_are_per_student(client, db, world, lesson, make_student):
    other, headers = make_student(first_name="Сараа")
    h.enroll(db, world.cohort, other)
    url = f"/me/lessons/{lesson.id}/note"
    client.put(url, headers=world.headers, json={"content": "mine"})
    resp = client.put(url, headers=headers, json={"content": "theirs"})
    assert resp.status_code == 201
    assert resp.get_json()["author"] == {"name": "Сараа", "initials": "С"}
    detail = client.get(f"/me/lessons/{lesson.id}", headers=world.headers).get_json()
    assert detail["note"]["content"] == "mine"


def test_note_errors(client, db, world, lesson, make_student, make_course):
    url = f"/me/lessons/{lesson.id}/note"
    assert client.put(url, json={"content": "x"}).status_code == 401
    resp = client.put(url, headers=make_student()[1], json={"content": "x"})
    assert (resp.status_code, resp.get_json()["error"]) == (403, "not_enrolled")
    resp = client.put("/me/lessons/987/note", headers=world.headers, json={"content": "x"})
    assert (resp.status_code, resp.get_json()["error"]) == (404, "lesson_not_found")


# ---------------------------------------------------------------- download
def test_download_file(client, db, world, lesson, s3):
    material = h.material(db, lesson, "Deck", size_bytes=10485760)
    resp = client.get(f"/me/materials/{material.id}/download", headers=world.headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["url"] == "https://s3.test/k/Deck?expires=300"
    assert data["file_name"] == "Deck.pdf"
    assert data["size_bytes"] == 10485760
    assert data["expires_at"].endswith("+00:00")


def test_download_own_cohort_material(client, db, world, lesson, s3):
    material = h.material(db, lesson, "Mine", cohort=world.cohort)
    resp = client.get(f"/me/materials/{material.id}/download", headers=world.headers)
    assert resp.status_code == 200


def test_download_other_cohort_material_is_404(client, db, world, lesson, s3, make_cohort):
    material = h.material(db, lesson, "Theirs", cohort=make_cohort(world.course))
    resp = client.get(f"/me/materials/{material.id}/download", headers=world.headers)
    assert (resp.status_code, resp.get_json()["error"]) == (404, "material_not_found")


def test_download_link_material(client, db, world, lesson, s3):
    material = h.material(db, lesson, "Link", type="link", url="https://x.test/doc",
                          file_key=None)
    resp = client.get(f"/me/materials/{material.id}/download", headers=world.headers)
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "material_is_link", "url": "https://x.test/doc"}


def test_download_storage_error(client, db, world, lesson, s3):
    material = h.material(db, lesson)
    s3.fail.add("presign")
    resp = client.get(f"/me/materials/{material.id}/download", headers=world.headers)
    assert (resp.status_code, resp.get_json()["error"]) == (503, "storage_error")


def test_download_errors(client, db, world, lesson, s3, make_student, make_course):
    material = h.material(db, lesson)
    url = f"/me/materials/{material.id}/download"
    assert client.get(url).status_code == 401
    resp = client.get(url, headers=make_student()[1])
    assert (resp.status_code, resp.get_json()["error"]) == (403, "not_enrolled")
    resp = client.get("/me/materials/555/download", headers=world.headers)
    assert (resp.status_code, resp.get_json()["error"]) == (404, "material_not_found")
    foreign = h.material(db, h.lesson(db, h.module(db, make_course())))
    resp = client.get(f"/me/materials/{foreign.id}/download", headers=world.headers)
    assert (resp.status_code, resp.get_json()["error"]) == (403, "not_enrolled")


def test_material_dict_helper(db, world, lesson):
    from app.services.learning import material_dict

    material = h.material(db, lesson, "Deck")
    assert material_dict(material) == {
        "id": material.id, "title": "Deck", "type": "file", "file_name": "Deck.pdf",
        "content_type": "application/pdf", "size_bytes": 1234}
