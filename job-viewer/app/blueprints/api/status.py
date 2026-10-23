from flask import Blueprint, jsonify, redirect, request
from flask_login import current_user, login_required

from ...extensions import db
from ...models import User
from ...services.auth import api_login_required
from ...services.jobs import create_prefect_job, list_user_jobs

api_status_bp = Blueprint("api_status", __name__)


@api_status_bp.route("/profile/update", methods=["POST"])
@login_required
def update_profile():
    data = request.get_json()
    new_username = data.get("username", "").strip()

    if not new_username:
        return jsonify({"status": "error", "message": "Username cannot be empty"}), 400

    existing_user = User.query.filter_by(username=new_username).first()
    if existing_user and existing_user.id != current_user.id:
        return jsonify({"status": "error", "message": "Username already exists"}), 400

    current_user.username = new_username
    db.session.commit()
    return jsonify({"status": "success", "message": "Username updated successfully"})


@api_status_bp.route("/profile/change-password", methods=["POST"])
@login_required
def change_password():
    data = request.get_json()
    current_pw = data.get("current_password")
    new_pw = data.get("new_password")
    confirm_pw = data.get("confirm_password")

    if not all([current_pw, new_pw, confirm_pw]):
        return jsonify({"status": "error", "message": "All fields are required"}), 400

    if not current_user.check_password(current_pw):
        return jsonify({"status": "error", "message": "Current password incorrect"}), 400

    if new_pw != confirm_pw:
        return jsonify({"status": "error", "message": "New passwords do not match"}), 400

    current_user.set_password(new_pw)
    db.session.commit()
    return jsonify({"status": "success", "message": "Password updated successfully"})


@api_status_bp.route("/api/dag/<dag_id>/run/<run_id>", methods=["GET"])
@api_login_required
def get_dag_run_details_ajax(dag_id: str, run_id: str):
    """Legacy path; redirects to GET /api/v1/jobs/<job_id>/status."""
    return redirect(f"/api/v1/jobs/{run_id}/status", code=302)


@api_status_bp.route("/submit", methods=["POST"])
@api_login_required
def post_submit():
    data = request.get_json(silent=True) or {}
    body, status = create_prefect_job(current_user, data)
    return jsonify(body), status


@api_status_bp.route("/user/<user_id>/submissions", methods=["GET"])
@api_login_required
def get_user_submitions_ajax(user_id: int):
    if int(user_id) != current_user.id and not current_user.is_admin():
        abort(403)

    user = User.query.filter_by(id=user_id).one_or_none()
    if not user:
        return jsonify({"status": "failed"})

    query_str = request.args.get("q", "").strip()
    result = list_user_jobs(
        user,
        query_str,
        page=request.args.get("page", 1),
        per_page=request.args.get("per_page", 25),
    )
    return jsonify({"status": "successful", **result})
