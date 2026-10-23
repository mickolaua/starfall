"""MVC Flask application factory for job-viewer."""

import os
import secrets
from pathlib import Path

from flask import Flask

try:
    from config import Config
except ImportError:  # loaded as a nested package (e.g. job-viewer.app)
    from ..config import Config

from .compat import install_template_url_for
from .extensions import babel, bootstrap, db, login_manager, migrate


def create_app(config_object=Config):
    package_dir = Path(__file__).resolve().parent
    job_viewer_root = package_dir.parent

    app = Flask(
        __name__,
        template_folder=str(job_viewer_root / "templates"),
        static_folder=str(job_viewer_root / "static"),
    )
    app.config.from_object(config_object)

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["RESULT_FOLDER"], exist_ok=True)

    app.secret_key = app.config.get("SECRET_KEY") or secrets.token_hex(16)
    if not app.config.get("SECRET_KEY"):
        app.logger.warning(
            "SECRET_KEY is not set; using an ephemeral key (sessions reset on restart)."
        )

    db.init_app(app)
    migrate.init_app(app, db, directory=str(job_viewer_root / "migrations"))
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    bootstrap.init_app(app)
    babel.init_app(app)

    from .models import Job, Setting, User  # noqa: F401 — register models with SQLAlchemy
    from .models.role import Permission, Role, RolePermission, UserRole  # noqa: F401
    from .services.auth import load_user_from_request
    from .services.rbac import ensure_default_roles_and_permissions
    from .services.settings import allow_self_registration

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    login_manager.request_loader(load_user_from_request)

    @app.context_processor
    def inject_site_settings():
        return {"allow_self_registration": allow_self_registration()}

    from .blueprints import register_blueprints

    register_blueprints(app)
    install_template_url_for(app)

    # Tables for brand-new DBs; column evolution via Flask-Migrate (flask db upgrade).
    with app.app_context():
        db.create_all()
        ensure_default_roles_and_permissions()

    return app
