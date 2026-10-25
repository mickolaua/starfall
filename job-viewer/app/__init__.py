"""MVC Flask application factory for job-viewer."""

import os
import secrets
from pathlib import Path
import logging.config

from flask import Flask, url_for

try:
    from config import Config
except ImportError:  # loaded as a nested package (e.g. job-viewer.app)
    from ..config import Config

from .compat import install_template_url_for
from .extensions import babel, bootstrap, db, login_manager, migrate, talisman, csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


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

    app.secret_key = app.config.get("SECRET_KEY")
    if not app.config.get("SECRET_KEY"):
        raise ValueError(
            "No secret key set.\nTip: set SECRET_KEY environmental variable and "
            "restart the application."
        )

    db.init_app(app)
    migrate.init_app(app, db, directory=str(job_viewer_root / "migrations"))
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    bootstrap.init_app(app)
    babel.init_app(app)
    # csrf.init_app(app)

    talisman.init_app(
        app,
        force_https=bool(app.config["TALISMAN_ENABLE_STRICT_HTTPS"]),
        content_security_policy= {
            'default-src': "'self'",
            'font-src': [
                "'self'",
                #"'{nonce}'",          # Formats the nonce string safely into the header mapping
                # "'unsafe-inline'",    # Fallback to allow Swagger's self-generated script-src-elem threads
                "https://cdn.jsdelivr.net",      # Whitelists Bootstrap Icons CSS CDN
                "https://fonts.googleapis.com",
                "https://fonts.gstatic.com"    # Whitelists Google Fonts CSS API
            ],
            'script-src': [
                "'self'",
                "'unsafe-hashes'",
                #"'{nonce}'",          # Formats the nonce string safely into the header mapping
                # "'unsafe-inline'",    # Fallback to allow Swagger's self-generated script-src-elem threads
                # "'unsafe-eval'",       # Stops dynamic runtime execution blocks from failing
                "https://cdn.jsdelivr.net",      # Whitelists Bootstrap Icons CSS CDN
                "https://unpkg.com",
            ],
            'style-src': [
                "'self'",
                "'unsafe-hashes'",
                #"'{nonce}'",
                # "'unsafe-inline'",     # Required for Swagger CSS stylesheet injection
                "https://cdn.jsdelivr.net",      # Whitelists Bootstrap Icons CSS CDN
                "https://fonts.googleapis.com",    # Whitelists Google Fonts CSS API
                "https://unpkg.com",
            ],
            'img-src': ["'self'", "data:"]
        },
        content_security_policy_nonce_in=['script-src', 'style-src', 'font-src'],
        # TODO: CSP violations reporting
        # content_security_policy_report_only=bool(app.config["CSP_REPORT_ONLY"]),
        # content_security_policy_report_uri=app.config["CSP_REPORT_ONLY"]"/api/v1/csp-report"
    )

    limiter = Limiter(
        get_remote_address,
        default_limits=app.config["LIMITER_DEFAULT_LIMITS"],
        storage_uri=app.config["LIMITER_STORAGE_URI"],
    )
    limiter.init_app(app)

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

    # Set up logging
    log_folder = Path(app.config["LOGS_FOLDER"]).resolve()
    log_folder.mkdir(parents=True, exist_ok=True)
    ini_path = log_folder / app.config["LOGS_CONFIG_FILENAME"]
    # logging.config.fileConfig(ini_path, disable_existing_loggers=False)

    return app
