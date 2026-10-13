from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), nullable=False, default="user")
    signup_datetime = db.Column(
        db.DateTime, nullable=False, default=datetime.now(timezone.utc)
    )
    last_login_datetime = db.Column(
        db.DateTime, nullable=False, default=datetime.now(timezone.utc)
    )

    jobs = db.relationship("Job", back_populates="user")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_banned(self) -> bool:
        return self.role == "banned"

    def is_admin(self) -> bool:
        return self.role == "admin"
