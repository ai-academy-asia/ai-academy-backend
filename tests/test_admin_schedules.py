"""Period-wide teacher / classroom schedule overviews (/admin/schedule/*)."""
from datetime import date

import pytest

PATHS = ["/admin/schedule/teachers", "/admin/schedule/classrooms"]


@pytest.fixture
def sales_headers(make_staff):
    return make_staff("sales_enrollment")[1]


@pytest.fixture
def world(make_teacher, make_classroom, make_cohort):
    """Two teachers / rooms: Dorj + Lab busy in Oct-Dec 2026, Saraa + Hall free."""
    busy_t, _ = make_teacher(first_name="Dorj", last_name="Bat")
    free_t, _ = make_teacher(first_name="Saraa")
    busy_r = make_classroom(name="Lab", center_name="Central", capacity=30)
    free_r = make_classroom(name="Hall", center_name="Central")
    autumn = make_cohort(teacher_id=busy_t.actor_id, classroom_id=busy_r.id,
                         start_date=date(2026, 10, 1), end_date=date(2026, 12, 1))
    spring = make_cohort(teacher_id=busy_t.actor_id, classroom_id=busy_r.id,
                         start_date=date(2027, 3, 1), end_date=date(2027, 5, 1))
    undated = make_cohort(teacher_id=busy_t.actor_id, start_date=None, end_date=None)
    return {"busy_t": busy_t.actor_id, "free_t": free_t.actor_id, "busy_r": busy_r.id,
            "free_r": free_r.id, "autumn": autumn.id, "spring": spring.id,
            "undated": undated.id}


# ---------------------------------------------------------------- auth
@pytest.mark.parametrize("path", PATHS)
def test_requires_token(client, path):
    resp = client.get(path)
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("role", ["finance", "content_marketing"])
def test_forbidden_without_schedule_manage(client, make_staff, path, role):
    _, headers = make_staff(role)
    resp = client.get(path, headers=headers)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


@pytest.mark.parametrize("path", PATHS)
def test_forbidden_for_teachers(client, make_teacher, path):
    _, headers = make_teacher()
    assert client.get(path, headers=headers).status_code == 403


# ---------------------------------------------------------------- range parsing
@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("query", ["from=2026-10-01", "to=2026-10-01"])
def test_from_and_to_go_together(client, sales_headers, path, query):
    resp = client.get(f"{path}?{query}", headers=sales_headers)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "from_and_to_required"


@pytest.mark.parametrize("path", PATHS)
def test_rejects_bad_dates(client, sales_headers, path):
    resp = client.get(f"{path}?from=2026-10-01&to=31/12/2026", headers=sales_headers)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_date"


# ---------------------------------------------------------------- teachers
def test_teachers_without_range_counts_every_cohort(client, sales_headers, world):
    resp = client.get("/admin/schedule/teachers", headers=sales_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["from"] is None and body["to"] is None
    assert body["count"] == 2
    busy, free = body["teachers"]
    assert busy["teacher"] == {"id": world["busy_t"], "name": "Dorj Bat"}
    assert busy["busy"] is True
    assert busy["cohort_count"] == 3
    # dated cohorts first, by start date; undated last
    assert [c["id"] for c in busy["cohorts"]] == [world["autumn"], world["spring"],
                                                  world["undated"]]
    assert free == {"teacher": {"id": world["free_t"], "name": "Saraa"},
                    "busy": False, "cohort_count": 0, "cohorts": []}


def test_teachers_range_keeps_overlapping_dated_cohorts(client, sales_headers, world):
    body = client.get("/admin/schedule/teachers?from=2026-11-15&to=2027-01-31",
                      headers=sales_headers).get_json()
    assert body["from"] == "2026-11-15" and body["to"] == "2027-01-31"
    busy = next(t for t in body["teachers"] if t["teacher"]["id"] == world["busy_t"])
    assert [c["id"] for c in busy["cohorts"]] == [world["autumn"]]


def test_teachers_range_boundaries_are_inclusive(client, sales_headers, world):
    body = client.get("/admin/schedule/teachers?from=2026-12-01&to=2026-12-01",
                      headers=sales_headers).get_json()
    busy = next(t for t in body["teachers"] if t["teacher"]["id"] == world["busy_t"])
    assert busy["cohort_count"] == 1


def test_teachers_available_filter(client, sales_headers, world):
    body = client.get("/admin/schedule/teachers?from=2026-10-01&to=2026-10-31&available=true",
                      headers=sales_headers).get_json()
    assert body["count"] == 1
    assert [t["teacher"]["id"] for t in body["teachers"]] == [world["free_t"]]

    # outside every cohort: everyone is free
    body = client.get("/admin/schedule/teachers?from=2026-01-01&to=2026-02-01&available=true",
                      headers=sales_headers).get_json()
    assert body["count"] == 2

    # only the literal "true" filters
    body = client.get("/admin/schedule/teachers?from=2026-10-01&to=2026-10-31&available=1",
                      headers=sales_headers).get_json()
    assert body["count"] == 2


def test_teachers_empty(client, admin_headers):
    body = client.get("/admin/schedule/teachers", headers=admin_headers).get_json()
    assert body == {"from": None, "to": None, "count": 0, "teachers": []}


# ---------------------------------------------------------------- classrooms
def test_classrooms_without_range(client, sales_headers, world):
    resp = client.get("/admin/schedule/classrooms", headers=sales_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["count"] == 2
    # ordered by center then name: Hall before Lab
    hall, lab = body["classrooms"]
    assert hall["classroom"]["id"] == world["free_r"]
    assert hall["busy"] is False and hall["cohorts"] == []
    assert lab["classroom"] == {"id": world["busy_r"], "name": "Lab", "center_name": "Central",
                                "capacity": 30, "is_active": True}
    assert lab["busy"] is True
    assert [c["id"] for c in lab["cohorts"]] == [world["autumn"], world["spring"]]


def test_classrooms_range(client, sales_headers, world):
    body = client.get("/admin/schedule/classrooms?from=2027-04-01&to=2027-04-30",
                      headers=sales_headers).get_json()
    lab = next(c for c in body["classrooms"] if c["classroom"]["id"] == world["busy_r"])
    assert [c["id"] for c in lab["cohorts"]] == [world["spring"]]
    assert lab["cohort_count"] == 1


def test_classrooms_available_filter(client, sales_headers, world):
    body = client.get("/admin/schedule/classrooms?from=2026-10-01&to=2026-10-31"
                      "&available=true", headers=sales_headers).get_json()
    assert [c["classroom"]["id"] for c in body["classrooms"]] == [world["free_r"]]
    assert body["count"] == 1


def test_classrooms_available_without_range(client, admin_headers, world):
    body = client.get("/admin/schedule/classrooms?available=true",
                      headers=admin_headers).get_json()
    assert [c["classroom"]["id"] for c in body["classrooms"]] == [world["free_r"]]
