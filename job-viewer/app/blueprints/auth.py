from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request
from flask_login import login_required, login_user, logout_user

from ..compat import url_for
from ..extensions import db, limit_from_config, limiter
from ..models import User
from ..services.auth import safe_next_url
from ..services.settings import allow_self_registration

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(limit_from_config("LIMITER_AUTH"), methods=["POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if user and user.is_banned():
            flash("You were banned")
            return render_template("login.html")

        if user and user.check_password(password):
            login_user(user)
            user.last_login_datetime = datetime.now(timezone.utc)
            db.session.commit()
            next_page = safe_next_url(request.args.get("next"))
            return redirect(next_page or url_for("user_page"))
        flash("Invalid username or password")
    return render_template("login.html")


@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit(limit_from_config("LIMITER_AUTH"), methods=["POST"])
def signup():
    if not allow_self_registration():
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if User.query.filter_by(username=username).first():
            flash("Username already exists")
        else:
            new_user = User(username=username)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.flush()
            new_user.set_roles(["user"])
            db.session.commit()
            flash("Registration successful! You can now log in.")
            return redirect(url_for("login"))
    return render_template("signup.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))
