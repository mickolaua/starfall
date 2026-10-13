import secrets
from functools import wraps

from flask import abort, current_app, flash, redirect, request
from flask_login import current_user

from ..compat import url_for


def role_required(role):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login", next=request.url))
            if current_user.role != role:
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
