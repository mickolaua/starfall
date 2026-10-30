"""Persisted site settings (key/value)."""

from ..extensions import db
from ..models.setting import Setting

ALLOW_SELF_REGISTRATION = "allow_self_registration"

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def get_setting(key: str, default: str | None = None) -> str | None:
    row = Setting.query.filter_by(key=key).one_or_none()
    if row is None:
        return default
    return row.value


def set_setting(key: str, value: str) -> None:
    row = Setting.query.filter_by(key=key).one_or_none()
    if row is None:
        row = Setting(key=key, value=value)
        db.session.add(row)
    else:
        row.value = value
    db.session.commit()


def get_bool(key: str, default: bool = True) -> bool:
    raw = get_setting(key)
    if raw is None:
        return default
    lowered = raw.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    return default


def set_bool(key: str, enabled: bool) -> None:
    set_setting(key, "true" if enabled else "false")


def allow_self_registration() -> bool:
    return get_bool(ALLOW_SELF_REGISTRATION, default=True)


def set_allow_self_registration(enabled: bool) -> None:
    set_bool(ALLOW_SELF_REGISTRATION, enabled)


def ensure_default_settings() -> None:
    """Idempotent seed of required Setting rows (e.g. self-registration flag)."""
    if get_setting(ALLOW_SELF_REGISTRATION) is None:
        set_setting(ALLOW_SELF_REGISTRATION, "true")
