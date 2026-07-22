from flask import Flask, jsonify

from .config import Config
from .extensions import db, migrate


def create_app(config_class: type = Config) -> Flask:
    """Application factory."""
    app = Flask(__name__)
    app.config.from_object(config_class)

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
        return jsonify(error=exc.code, **exc.extra), exc.status

    # Register actor routers (health, auth, student, teacher, admin)
    from .routes import register_blueprints

    register_blueprints(app)

    # CLI commands (flask auth create-staff ...)
    from .cli import register_cli

    register_cli(app)

    return app
