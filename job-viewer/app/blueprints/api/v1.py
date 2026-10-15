from flask import Blueprint, jsonify, request
from flask_login import current_user

from ...services.auth import (
    api_login_required,
    revoke_user_api_token,
    rotate_user_api_token,
)
from ...services.jobs import (
    create_prefect_job,
    get_job_status_payload,
    list_user_jobs,
    rename_job,
    store_uploaded_frames,
)

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


@api_v1_bp.route("/auth/token", methods=["POST"])
@api_login_required
def create_or_rotate_token():
    raw = rotate_user_api_token(current_user)
    return jsonify(
        {
            "status": "successful",
            "token": raw,
            "token_type": "Bearer",
            "message": "Store this token securely; it will not be shown again.",
        }
    )


@api_v1_bp.route("/auth/token", methods=["DELETE"])
@api_login_required
def revoke_token():
    revoke_user_api_token(current_user)
    return jsonify({"status": "successful", "message": "API token revoked"})


@api_v1_bp.route("/auth/token", methods=["GET"])
@api_login_required
def token_status():
    return jsonify(
        {
            "status": "successful",
            "has_token": current_user.has_api_token(),
        }
    )


@api_v1_bp.route("/jobs/upload", methods=["POST"])
@api_login_required
def upload_job_frames():
    lights = request.files.getlist("lights")
    darks = request.files.getlist("darks")
    flats = request.files.getlist("flats")
    result = store_uploaded_frames(current_user, lights, darks, flats)
    if isinstance(result, tuple):
        return jsonify({"status": "failed", "uploaded": 0, "reason": result[1]}), 400
    return jsonify(result)


@api_v1_bp.route("/jobs", methods=["POST"])
@api_login_required
def create_job():
    data = request.get_json(silent=True) or {}
    body, status = create_prefect_job(current_user, data)
    return jsonify(body), status


@api_v1_bp.route("/jobs", methods=["GET"])
@api_login_required
def list_jobs():
    query = request.args.get("q", "").strip()
    result = list_user_jobs(
        current_user,
        query,
        page=request.args.get("page", 1),
        per_page=request.args.get("per_page", 25),
    )
    return jsonify({"status": "successful", **result})


@api_v1_bp.route("/jobs/<job_id>", methods=["GET"])
@api_login_required
def get_job(job_id: str):
    body, status = get_job_status_payload(current_user, job_id)
    return jsonify(body), status


@api_v1_bp.route("/jobs/<job_id>", methods=["PATCH"])
@api_login_required
def patch_job(job_id: str):
    data = request.get_json(silent=True) or {}
    if "name" not in data:
        return jsonify({"status": "failed", "reason": "name field required"}), 400
    body, status = rename_job(current_user, job_id, data.get("name"))
    return jsonify(body), status
