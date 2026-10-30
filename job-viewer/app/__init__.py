"""MVC Flask application factory for job-viewer."""

import os
from pathlib import Path

from flask import Flask

try:
    from config import Config
except ImportError:  # loaded as a nested package (e.g. job-viewer.app)
    from ..config import Config

from .compat import install_template_url_for
from .extensions import babel, bootstrap, csrf, db, limiter, login_manager, migrate, talisman


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
    csrf.init_app(app)

    talisman_kwargs = {
        "force_https": bool(app.config.get("TALISMAN_FORCE_HTTPS")),
        "content_security_policy": app.config.get("TALISMAN_CONTENT_SECURITY_POLICY"),
        "content_security_policy_nonce_in": app.config.get(
            "TALISMAN_CONTENT_SECURITY_POLICY_NONCE_IN"
        ),
        "content_security_policy_report_only": bool(
            app.config.get("TALISMAN_CSP_REPORT_ONLY")
        ),
        "frame_options": app.config.get("TALISMAN_FRAME_OPTIONS") or "SAMEORIGIN",
    }
    report_uri = (app.config.get("TALISMAN_CSP_REPORT_URI") or "").strip()
    if report_uri:
        talisman_kwargs["content_security_policy_report_uri"] = report_uri
    hsts = (app.config.get("TALISMAN_STRICT_TRANSPORT_SECURITY") or "").strip()
    if hsts:
        talisman_kwargs["strict_transport_security"] = True
        # Talisman uses force_https + defaults; custom max-age via config string
        # is applied when force_https is on. Keep explicit only if provided.
        if hsts.startswith("max-age="):
            try:
                talisman_kwargs["strict_transport_security_max_age"] = int(
                    hsts.split(";")[0].split("=", 1)[1].strip()
                )
            except (IndexError, ValueError):
                pass

    talisman.init_app(app, **talisman_kwargs)

    app.config["RATELIMIT_STORAGE_URI"] = app.config["LIMITER_STORAGE_URI"]
    limiter.init_app(app)
    app.extensions["limiter"] = limiter

    from .models import Job, Setting, User  # noqa: F401 — register models with SQLAlchemy
    from .models.role import Permission, Role, RolePermission, UserRole  # noqa: F401
    from .services.auth import load_user_from_request
    from .services.rbac import ensure_default_roles_and_permissions
    from .services.settings import allow_self_registration, ensure_default_settings

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

    # CSRF: protect HTML forms; exempt token/callback/session AJAX APIs.
    from .blueprints.api.callbacks import callbacks_bp
    from .blueprints.api.docs import api_docs_bp
    from .blueprints.api.jobs import api_jobs_bp
    from .blueprints.api.status import api_status_bp
    from .blueprints.api.v1 import api_v1_bp

    for bp in (api_v1_bp, api_jobs_bp, api_status_bp, callbacks_bp, api_docs_bp):
        csrf.exempt(bp)

    # Tables for brand-new DBs; column evolution via Flask-Migrate (flask db upgrade).
    with app.app_context():
        db.create_all()
        ensure_default_roles_and_permissions()
        ensure_default_settings()

    log_folder = Path(app.config["LOGS_FOLDER"]).resolve()
    log_folder.mkdir(parents=True, exist_ok=True)

    return app
