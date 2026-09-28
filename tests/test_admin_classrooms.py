"""Classroom CRUD (/admin/classrooms) — super_admin only."""
import pytest

from app.models import Classroom, Cohort


def _fresh(db, model, pk):
    db.session.expire_all()
    return db.session.get(model, pk)


# ---------------------------------------------------------------- auth
@pytest.mark.parametrize("method,path", [
    ("get", "/admin/classrooms"), ("post", "/admin/classrooms"),
    ("get", "/admin/classrooms/1"), ("patch", "/admin/classrooms/1"),
    ("delete", "/admin/classrooms/1"),
])
def test_requires_token(client, method, path):
    resp = getattr(client, method)(path, json={})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


@pytest.mark.parametrize("role", ["sales_enrollment", "finance", "content_marketing"])
def test_only_super_admin_may_manage(client, make_staff, make_classroom, role):
    room = make_classroom()
    _, headers = make_staff(role)
    for method, path in [
        ("get", "/admin/classrooms"), ("post", "/admin/classrooms"),
        ("get", f"/admin/classrooms/{room.id}"), ("patch", f"/admin/classrooms/{room.id}"),
        ("delete", f"/admin/classrooms/{room.id}"),
    ]:
        resp = getattr(client, method)(path, json={"name": "X"}, headers=headers)
        assert resp.status_code == 403, (method, path)
        assert resp.get_json()["error"] == "forbidden"
    assert Classroom.query.count() == 1


def test_students_and_teachers_are_forbidden(client, make_student, make_teacher):
    for _, headers in (make_student(), make_teacher()):
        assert client.get("/admin/classrooms", headers=headers).status_code == 403


# ---------------------------------------------------------------- list / get
def test_list_orders_by_center_then_name(client, admin_headers, make_classroom):
    make_classroom(name="B", center_name="Zaisan")
    make_classroom(name="B", center_name="Central")
    make_classroom(name="A", center_name="Central")
    body = client.get("/admin/classrooms", headers=admin_headers).get_json()
    assert [(c["center_name"], c["name"]) for c in body["classrooms"]] == [
        ("Central", "A"), ("Central", "B"), ("Zaisan", "B"),
    ]


def test_list_search_and_active_filter(client, admin_headers, make_classroom):
    make_classroom(name="Lab 1", center_name="Central")
    make_classroom(name="Room 2", center_name="Zaisan Lab", is_active=False)
    make_classroom(name="Hall", center_name="Central")

    body = client.get("/admin/classrooms?q=lab", headers=admin_headers).get_json()
    assert {c["name"] for c in body["classrooms"]} == {"Lab 1", "Room 2"}

    body = client.get("/admin/classrooms?active=false", headers=admin_headers).get_json()
    assert [c["name"] for c in body["classrooms"]] == ["Room 2"]

    body = client.get("/admin/classrooms?active=true&q=lab", headers=admin_headers).get_json()
    assert [c["name"] for c in body["classrooms"]] == ["Lab 1"]

    # anything but true/false is ignored
    body = client.get("/admin/classrooms?active=maybe", headers=admin_headers).get_json()
    assert len(body["classrooms"]) == 3


def test_get_returns_classroom(client, admin_headers, make_classroom):
    room = make_classroom(name="Lab", capacity=30, equipment=["projector"])
    resp = client.get(f"/admin/classrooms/{room.id}", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == room.id
    assert body["name"] == "Lab"
    assert body["capacity"] == 30
    assert body["equipment"] == ["projector"]


def test_get_unknown_is_404(client, admin_headers):
    resp = client.get("/admin/classrooms/9999", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------- create
def test_create_classroom(client, admin_headers, db):
    resp = client.post("/admin/classrooms", headers=admin_headers, json={
        "name": "Room 301", "center_name": "Central", "location": "Seoul st 1",
        "capacity": 24, "floor": "3", "equipment": ["projector", "30 PCs"],
        "notes": "quiet", "id": 777, "created_at": "2000-01-01",
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["id"] != 777
    assert body["is_active"] is True
    room = db.session.get(Classroom, body["id"])
    assert room.name == "Room 301"
    assert room.equipment == ["projector", "30 PCs"]
    assert room.floor == "3"


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"center_name": "Central"}])
def test_create_requires_name(client, admin_headers, payload):
    resp = client.post("/admin/classrooms", headers=admin_headers, json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "name_required"
    assert Classroom.query.count() == 0


def test_create_duplicate_in_same_center_is_409(client, admin_headers, make_classroom):
    make_classroom(name="Lab", center_name="Central")
    resp = client.post("/admin/classrooms", headers=admin_headers,
                       json={"name": "Lab", "center_name": "Central"})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "classroom_exists"

    resp = client.post("/admin/classrooms", headers=admin_headers,
                       json={"name": "Lab", "center_name": "Zaisan"})
    assert resp.status_code == 201


# ---------------------------------------------------------------- update
def test_update_classroom(client, admin_headers, make_classroom, db):
    room = make_classroom(name="Lab", capacity=10)
    rid = room.id
    resp = client.patch(f"/admin/classrooms/{rid}", headers=admin_headers,
                        json={"capacity": 40, "is_active": False})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["capacity"] == 40
    assert body["is_active"] is False
    assert body["name"] == "Lab"
    assert _fresh(db, Classroom, rid).capacity == 40


def test_update_cannot_blank_name(client, admin_headers, make_classroom, db):
    room = make_classroom(name="Lab")
    rid = room.id
    resp = client.patch(f"/admin/classrooms/{rid}", headers=admin_headers, json={"name": ""})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "name_required"
    db.session.rollback()  # requests share the fixture's app context; mimic teardown
    assert _fresh(db, Classroom, rid).name == "Lab"


def test_update_into_duplicate_is_409(client, admin_headers, make_classroom, db):
    make_classroom(name="Lab", center_name="Central")
    other = make_classroom(name="Hall", center_name="Central")
    oid = other.id
    resp = client.patch(f"/admin/classrooms/{oid}", headers=admin_headers, json={"name": "Lab"})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "classroom_exists"
    assert _fresh(db, Classroom, oid).name == "Hall"


def test_update_unknown_is_404(client, admin_headers):
    resp = client.patch("/admin/classrooms/9999", headers=admin_headers, json={"name": "X"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------- delete
def test_delete_classroom(client, admin_headers, make_classroom, db):
    rid = make_classroom().id
    resp = client.delete(f"/admin/classrooms/{rid}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "deleted"}
    assert _fresh(db, Classroom, rid) is None


def test_delete_classroom_unassigns_cohorts(client, admin_headers, make_classroom,
                                            make_cohort, db):
    rid = make_classroom().id
    cid = make_cohort(classroom_id=rid).id
    assert client.delete(f"/admin/classrooms/{rid}", headers=admin_headers).status_code == 200
    cohort = _fresh(db, Cohort, cid)
    assert cohort is not None
    assert cohort.classroom_id is None


def test_delete_unknown_is_404(client, admin_headers):
    resp = client.delete("/admin/classrooms/9999", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"
