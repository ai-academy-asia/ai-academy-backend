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

    # Register blueprints
    from .routes.health import bp as health_bp

    app.register_blueprint(health_bp)

    return app
