"""Service info and liveness."""


def test_index_reports_service(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.get_json()["service"] == "aiaa-backend"


def test_health_reports_database_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "database": True}


def test_health_degrades_when_database_is_unreachable(client, monkeypatch):
    from app.extensions import db

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(db.session, "execute", _boom)
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.get_json() == {"status": "degraded", "database": False}
