from flask import Flask

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

    # Register blueprints
    from .routes.admin_users import bp as admin_users_bp
    from .routes.auth import bp as auth_bp
    from .routes.courses import bp as courses_bp
    from .routes.health import bp as health_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(admin_users_bp)

    # CLI commands (flask auth create-staff ...)
    from .cli import register_cli

    register_cli(app)

    return app
