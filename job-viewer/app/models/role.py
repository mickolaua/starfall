import json

from ..extensions import db


class Role(db.Model):
    __tablename__ = "role"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)

    users = db.relationship(
        "User",
        secondary="user_role",
        back_populates="roles",
        lazy="select",
    )
    permissions = db.relationship(
        "Permission",
        secondary="role_permission",
        back_populates="roles",
        lazy="joined",
    )


class Permission(db.Model):
    __tablename__ = "permission"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    flags = db.Column(db.Text, nullable=False, default="{}")

    roles = db.relationship(
        "Role",
        secondary="role_permission",
        back_populates="permissions",
        lazy="select",
    )

    def get_flags(self) -> dict:
        if not self.flags:
            return {}
        try:
            data = json.loads(self.flags)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def set_flags(self, flags: dict | None) -> None:
        self.flags = json.dumps(flags or {}, ensure_ascii=False)


class UserRole(db.Model):
    __tablename__ = "user_role"
    __table_args__ = (
        db.UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id = db.Column(
        db.Integer, db.ForeignKey("role.id", ondelete="CASCADE"), nullable=False, index=True
    )


class RolePermission(db.Model):
    __tablename__ = "role_permission"
    __table_args__ = (
        db.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(
        db.Integer, db.ForeignKey("role.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id = db.Column(
        db.Integer,
        db.ForeignKey("permission.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
