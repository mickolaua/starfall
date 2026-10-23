import secrets
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    signup_datetime = db.Column(
        db.DateTime, nullable=False, default=datetime.now(timezone.utc)
    )
    last_login_datetime = db.Column(
        db.DateTime, nullable=False, default=datetime.now(timezone.utc)
    )
    # Lookup prefix (16 hex chars) + hash of full raw token. Raw token shown once.
    api_token_prefix = db.Column(db.String(16), unique=True, nullable=True, index=True)
    api_token_hash = db.Column(db.String(255), nullable=True)

    jobs = db.relationship("Job", back_populates="user")
    roles = db.relationship(
        "Role",
        secondary="user_role",
        back_populates="users",
        lazy="joined",
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def role_names(self) -> list[str]:
        return [r.name for r in (self.roles or [])]

    @property
    def primary_role_name(self) -> str:
        names = self.role_names
        if "admin" in names:
            return "admin"
        if "banned" in names:
            return "banned"
        if names:
            return names[0]
        return "user"

    def has_role(self, name: str) -> bool:
        return any(r.name == name for r in (self.roles or []))

    def has_permission(self, code: str) -> bool:
        for role in self.roles or []:
            for perm in role.permissions or []:
                if perm.code == code:
                    return True
        return False

    def permission_flags(self, code: str) -> dict:
        for role in self.roles or []:
            for perm in role.permissions or []:
                if perm.code == code:
                    return perm.get_flags()
        return {}

    def is_banned(self) -> bool:
        return self.has_permission("banned")

    def is_admin(self) -> bool:
        return self.has_permission("admin")

    def assign_role(self, name: str) -> None:
        from .role import Role

        role = Role.query.filter_by(name=name).one_or_none()
        if role is None:
            raise ValueError(f"Unknown role: {name}")
        if role not in self.roles:
            self.roles.append(role)

    def remove_role(self, name: str) -> None:
        self.roles = [r for r in (self.roles or []) if r.name != name]

    def set_roles(self, names: list[str]) -> None:
        from .role import Role

        wanted = []
        for name in names:
            role = Role.query.filter_by(name=name).one_or_none()
            if role is None:
                raise ValueError(f"Unknown role: {name}")
            wanted.append(role)
        self.roles = wanted

    def has_api_token(self) -> bool:
        return bool(self.api_token_hash and self.api_token_prefix)

    def set_api_token(self, raw_token: str) -> None:
        """Store hash of a raw token. Caller must set api_token_prefix separately."""
        self.api_token_hash = generate_password_hash(raw_token)

    def check_api_token(self, raw_token: str) -> bool:
        if not self.api_token_hash or not raw_token:
            return False
        return check_password_hash(self.api_token_hash, raw_token)

    def issue_api_token(self) -> str:
        """Generate, store, and return a new raw API token (shown once to the client)."""
        prefix = secrets.token_hex(8)
        secret = secrets.token_urlsafe(32)
        raw = f"{prefix}.{secret}"
        self.api_token_prefix = prefix
        self.set_api_token(raw)
        return raw

    def revoke_api_token(self) -> None:
        self.api_token_prefix = None
        self.api_token_hash = None
