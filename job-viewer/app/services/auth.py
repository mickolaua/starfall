import secrets
from functools import wraps

from flask import abort, current_app, flash, redirect, request
from flask_login import current_user

from ..compat import url_for
from ..extensions import db
from ..models import User


def role_required(role):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login", next=request.url))
            if not current_user.has_role(role):
                flash("You do not have permission to access this page.")
                return redirect(url_for("index"))
            return f(*args, **kwargs)

        return decorated_function

    return wrapper


def safe_next_url(candidate: str | None) -> str | None:
    """Allow only relative in-app redirects (block open redirects)."""
    if not candidate:
        return None
    candidate = candidate.strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return None
    if "\\" in candidate or "://" in candidate:
        return None
    return candidate


def callback_token_from_request() -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("X-JobViewer-Token") or "").strip()


def require_callback_token() -> None:
    expected = (current_app.config.get("JOBVIEWER_CALLBACK_TOKEN") or "").strip()
    provided = callback_token_from_request()
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        abort(401)


def bearer_token_from_request() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    return None


def find_user_by_api_token(raw_token: str) -> User | None:
    if not raw_token or "." not in raw_token:
        return None
    prefix = raw_token.split(".", 1)[0]
    if len(prefix) != 16:
        return None
    user = User.query.filter_by(api_token_prefix=prefix).one_or_none()
    if user is None or not user.check_api_token(raw_token):
        return None
    if user.is_banned():
        return None
    return user


def load_user_from_request(_request):
    """Flask-Login request_loader: authenticate via Bearer user API token."""
    raw = bearer_token_from_request()
    if not raw:
        return None
    # Never treat the worker callback secret as a user API token.
    expected_callback = (current_app.config.get("JOBVIEWER_CALLBACK_TOKEN") or "").strip()
    if expected_callback and secrets.compare_digest(raw, expected_callback):
        return None
    return find_user_by_api_token(raw)


def api_login_required(f):
    """Require session cookie or Bearer user token; return 401 JSON (no redirect)."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.is_banned():
            abort(403)
        return f(*args, **kwargs)

    return decorated


def rotate_user_api_token(user: User) -> str:
    raw = user.issue_api_token()
    db.session.commit()
    return raw


def revoke_user_api_token(user: User) -> None:
    user.revoke_api_token()
    db.session.commit()
