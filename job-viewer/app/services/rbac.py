"""Seed and ensure default roles / permissions."""

from __future__ import annotations

from ..extensions import db
from ..models.role import Permission, Role

_DEFAULT_PERMISSIONS = (
    {
        "code": "admin",
        "name": "Administrator access",
        "description": "Access admin panel and cross-user APIs",
        "flags": {},
    },
    {
        "code": "banned",
        "name": "Account banned",
        "description": "Blocks login and API access",
        "flags": {"block_login": True},
    },
)

_DEFAULT_ROLES = (
    {
        "name": "admin",
        "description": "Full administrator",
        "permissions": ("admin",),
    },
    {
        "name": "user",
        "description": "Default member",
        "permissions": (),
    },
    {
        "name": "banned",
        "description": "Banned account",
        "permissions": ("banned",),
    },
)


def ensure_default_roles_and_permissions() -> None:
    """Idempotent seed of permissions, roles, and role_permission links."""
    for spec in _DEFAULT_PERMISSIONS:
        perm = Permission.query.filter_by(code=spec["code"]).one_or_none()
        if perm is None:
            perm = Permission(
                code=spec["code"],
                name=spec["name"],
                description=spec.get("description"),
            )
            perm.set_flags(spec.get("flags") or {})
            db.session.add(perm)
        elif perm.flags in (None, ""):
            perm.set_flags(spec.get("flags") or {})

    db.session.flush()

    for spec in _DEFAULT_ROLES:
        role = Role.query.filter_by(name=spec["name"]).one_or_none()
        if role is None:
            role = Role(name=spec["name"], description=spec.get("description"))
            db.session.add(role)
            db.session.flush()

        wanted = []
        for code in spec["permissions"]:
            perm = Permission.query.filter_by(code=code).one()
            wanted.append(perm)
        # Ensure required permissions are present (do not strip extras).
        current = list(role.permissions or [])
        for perm in wanted:
            if perm not in current:
                current.append(perm)
        role.permissions = current

    db.session.commit()


def get_role_by_name(name: str) -> Role | None:
    return Role.query.filter_by(name=name).one_or_none()
