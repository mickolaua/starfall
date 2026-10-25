"""Flask extensions shared across the MVC app (initialized in create_app)."""

from flask_babel import Babel
from flask_bootstrap import Bootstrap
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_talisman import Talisman
from flask_wtf import CSRFProtect


__all__ = ["db", "migrate", "login_manager", "bootstrap", "babel", "talisman", "csrf"]

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
bootstrap = Bootstrap()
babel = Babel()
talisman = Talisman()
csrf = CSRFProtect()
