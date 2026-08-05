from flask import Flask, jsonify

from .config import Config
from .extensions import db, migrate

# Anything that identifies production. The database matters more than the URL:
# .env points DATABASE_URL at the Tokyo RDS even during local development, so a
# developer running the sandbox on localhost would otherwise write free
# settlements and real tax receipts straight into production.
_PRODUCTION_MARKERS = (
    "api.ai-academy.asia",
    "ai-academy.asia",
    "35.78.131.144",
    "rds.amazonaws.com",
)


def _check_sandbox(app: Flask) -> None:
    """Refuse to run the money-free payment stub against production."""
    if not app.config.get("PAYMENTS_SANDBOX"):
        return
    for key in ("PUBLIC_BASE_URL", "SQLALCHEMY_DATABASE_URI"):
        value = str(app.config.get(key) or "").lower()
        # Blank is not "safe by default". `os.getenv(k, default)` returns "" for
        # a variable that is *present but empty*, and deploys deliberately
        # preserve the server's .env, so `PUBLIC_BASE_URL=` would silently
        # disarm this check on the very host it exists to protect.
        if not value:
            raise RuntimeError(
                f"PAYMENTS_SANDBOX is on but {key} is empty, so there is no way "
                "to tell this apart from production. Set it explicitly."
            )
        hit = next((m for m in _PRODUCTION_MARKERS if m in value), None)
        if hit:
            raise RuntimeError(
                f"PAYMENTS_SANDBOX is on but {key} points at production "
                f"({hit}). Sandbox settles checkouts without payment and would "
                "issue real tax receipts. Unset PAYMENTS_SANDBOX, or point this "
                "at a local database."
            )
    app.logger.warning(
        "PAYMENTS_SANDBOX is ON — every checkout settles instantly with no "
        "money. Do not use this against real customers."
    )


def create_app(config_class: type = Config) -> Flask:
    """Application factory."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    _check_sandbox(app)

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)

    # Register models so Flask-Migrate can discover them
    from . import models  # noqa: F401

    # Auth request middleware (populates g.current_user when a Bearer token is present)
    from .auth import register_auth_middleware

    register_auth_middleware(app)

    # Service-layer errors -> JSON responses
    from .services.errors import ServiceError

    @app.errorhandler(ServiceError)
    def _handle_service_error(exc):  # noqa: ANN001
        internal = getattr(exc, "internal_detail", None)
        if internal is not None:
            app.logger.warning("%s upstream detail: %r", exc.code, internal)
        return jsonify(error=exc.code, **exc.extra), exc.status

    # Register actor routers (health, auth, student, teacher, admin)
    from .routes import register_blueprints

    register_blueprints(app)

    # CLI commands (flask auth create-staff ...)
    from .cli import register_cli

    register_cli(app)

    return app
