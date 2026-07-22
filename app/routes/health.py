from flask import Blueprint, jsonify
from sqlalchemy import text

from app.extensions import db

bp = Blueprint("health", __name__)


@bp.get("/")
def index():
    return jsonify(service="aiaa-backend", status="ok", version="1.1")


@bp.get("/health")
def health():
    """Liveness + DB connectivity check."""
    try:
        db.session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False

    status_code = 200 if db_ok else 503
    return jsonify(status="ok" if db_ok else "degraded", database=db_ok), status_code
