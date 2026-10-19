def register_blueprints(app) -> None:
    from .api.callbacks import callbacks_bp
    from .api.docs import api_docs_bp
    from .api.jobs import api_jobs_bp
    from .api.status import api_status_bp
    from .api.v1 import api_v1_bp
    from .auth import auth_bp
    from .pages import pages_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_jobs_bp)
    app.register_blueprint(api_status_bp)
    app.register_blueprint(api_v1_bp)
    app.register_blueprint(api_docs_bp)
    app.register_blueprint(callbacks_bp)
