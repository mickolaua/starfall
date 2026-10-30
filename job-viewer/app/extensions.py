"""Flask extensions shared across the MVC app (initialized in create_app)."""

from flask_babel import Babel
from flask_bootstrap import Bootstrap
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_talisman import Talisman
from flask_wtf import CSRFProtect


__all__ = [
    "db",
    "migrate",
    "login_manager",
    "bootstrap",
    "babel",
    "talisman",
    "csrf",
    "limiter",
    "limit_from_config",
]

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
bootstrap = Bootstrap()
babel = Babel()
talisman = Talisman()
csrf = CSRFProtect()
# No global default_limits — apply per-route via @limiter.limit(...).
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def limit_from_config(config_key: str):
    """Return a callable limit string read from current_app.config at request time."""

    def _limit():
        from flask import current_app

        return current_app.config[config_key]

    return _limit
