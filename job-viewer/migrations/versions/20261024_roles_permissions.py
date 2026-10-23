"""Roles, permissions, user_role, role_permission; drop user.role.

Revision ID: 20261024_rbac
Revises: 20261023_setting
Create Date: 2026-10-24
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "20261024_rbac"
down_revision = "20261023_setting"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    tables = _tables()

    if "permission" not in tables:
        op.create_table(
            "permission",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("flags", sa.Text(), nullable=False, server_default="{}"),
        )
        op.create_index("ix_permission_code", "permission", ["code"], unique=True)

    if "role" not in tables:
        op.create_table(
            "role",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=50), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
        )
        op.create_index("ix_role_name", "role", ["name"], unique=True)

    if "user_role" not in tables:
        op.create_table(
            "user_role",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role_id", sa.Integer(), sa.ForeignKey("role.id", ondelete="CASCADE"), nullable=False),
            sa.UniqueConstraint("user_id", "role_id", name="uq_user_role"),
        )
        op.create_index("ix_user_role_user_id", "user_role", ["user_id"])
        op.create_index("ix_user_role_role_id", "user_role", ["role_id"])

    if "role_permission" not in tables:
        op.create_table(
            "role_permission",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("role_id", sa.Integer(), sa.ForeignKey("role.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "permission_id",
                sa.Integer(),
                sa.ForeignKey("permission.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
        )
        op.create_index("ix_role_permission_role_id", "role_permission", ["role_id"])
        op.create_index("ix_role_permission_permission_id", "role_permission", ["permission_id"])

    conn = op.get_bind()

    def _ensure_perm(code: str, name: str, flags: dict) -> int:
        row = conn.execute(
            sa.text("SELECT id FROM permission WHERE code = :c"), {"c": code}
        ).fetchone()
        if row:
            return row[0]
        conn.execute(
            sa.text(
                "INSERT INTO permission (code, name, description, flags) "
                "VALUES (:code, :name, :desc, :flags)"
            ),
            {
                "code": code,
                "name": name,
                "desc": None,
                "flags": json.dumps(flags),
            },
        )
        return conn.execute(
            sa.text("SELECT id FROM permission WHERE code = :c"), {"c": code}
        ).fetchone()[0]

    def _ensure_role(name: str, description: str | None) -> int:
        row = conn.execute(
            sa.text("SELECT id FROM role WHERE name = :n"), {"n": name}
        ).fetchone()
        if row:
            return row[0]
        conn.execute(
            sa.text("INSERT INTO role (name, description) VALUES (:n, :d)"),
            {"n": name, "d": description},
        )
        return conn.execute(
            sa.text("SELECT id FROM role WHERE name = :n"), {"n": name}
        ).fetchone()[0]

    def _link_role_perm(role_id: int, perm_id: int) -> None:
        exists = conn.execute(
            sa.text(
                "SELECT 1 FROM role_permission "
                "WHERE role_id = :r AND permission_id = :p"
            ),
            {"r": role_id, "p": perm_id},
        ).fetchone()
        if exists:
            return
        conn.execute(
            sa.text(
                "INSERT INTO role_permission (role_id, permission_id) VALUES (:r, :p)"
            ),
            {"r": role_id, "p": perm_id},
        )

    admin_perm = _ensure_perm("admin", "Administrator access", {})
    banned_perm = _ensure_perm(
        "banned", "Account banned", {"block_login": True}
    )
    admin_role = _ensure_role("admin", "Full administrator")
    user_role = _ensure_role("user", "Default member")
    banned_role = _ensure_role("banned", "Banned account")
    _link_role_perm(admin_role, admin_perm)
    _link_role_perm(banned_role, banned_perm)

    role_map = {"admin": admin_role, "user": user_role, "banned": banned_role}

    if "role" in _columns("user"):
        users = conn.execute(sa.text("SELECT id, role FROM user")).fetchall()
        for user_id, old_role in users:
            role_id = role_map.get((old_role or "user").lower(), user_role)
            exists = conn.execute(
                sa.text(
                    "SELECT 1 FROM user_role WHERE user_id = :u AND role_id = :r"
                ),
                {"u": user_id, "r": role_id},
            ).fetchone()
            if not exists:
                conn.execute(
                    sa.text(
                        "INSERT INTO user_role (user_id, role_id) VALUES (:u, :r)"
                    ),
                    {"u": user_id, "r": role_id},
                )

        with op.batch_alter_table("user") as batch:
            batch.drop_column("role")
    else:
        # Fresh / already migrated: ensure every user has at least user role
        users = conn.execute(sa.text("SELECT id FROM user")).fetchall()
        for (user_id,) in users:
            exists = conn.execute(
                sa.text("SELECT 1 FROM user_role WHERE user_id = :u"),
                {"u": user_id},
            ).fetchone()
            if not exists:
                conn.execute(
                    sa.text(
                        "INSERT INTO user_role (user_id, role_id) VALUES (:u, :r)"
                    ),
                    {"u": user_id, "r": user_role},
                )


def downgrade() -> None:
    tables = _tables()
    if "role" not in _columns("user") and "user" in tables:
        with op.batch_alter_table("user") as batch:
            batch.add_column(
                sa.Column("role", sa.String(length=50), nullable=False, server_default="user")
            )

        conn = op.get_bind()
        # Best-effort restore from user_role primary role name
        rows = conn.execute(
            sa.text(
                "SELECT ur.user_id, r.name FROM user_role ur "
                "JOIN role r ON r.id = ur.role_id"
            )
        ).fetchall()
        by_user: dict[int, list[str]] = {}
        for uid, name in rows:
            by_user.setdefault(uid, []).append(name)
        for uid, names in by_user.items():
            if "admin" in names:
                label = "admin"
            elif "banned" in names:
                label = "banned"
            else:
                label = "user"
            conn.execute(
                sa.text("UPDATE user SET role = :role WHERE id = :id"),
                {"role": label, "id": uid},
            )

    for table in ("role_permission", "user_role", "permission", "role"):
        if table in _tables():
            op.drop_table(table)
