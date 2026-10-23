from flask import Blueprint, abort, jsonify, request
from flask_login import current_user

from ...models import Job, User
from ...services.auth import (
    api_login_required,
    revoke_user_api_token,
    rotate_user_api_token,
)
from ...services.jobs import (
    accessible_job,
    attach_reused_frames,
    create_job_shell,
    create_prefect_job,
    delete_job,
    get_job_status_payload,
    list_reusable_files,
    list_user_jobs,
    rename_job,
    retry_job,
    store_uploaded_frames,
    sync_job_status_from_prefect,
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


@api_v1_bp.route("/jobs/shell", methods=["POST"])
@api_login_required
def create_empty_job_shell():
    return jsonify(create_job_shell(current_user))


@api_v1_bp.route("/jobs/reuse", methods=["POST"])
@api_login_required
def reuse_job_frames():
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    mode = data.get("mode") or "copy"
    delete_source = bool(data.get("delete_source"))
    result = attach_reused_frames(
        current_user,
        items,
        mode=mode,
        delete_source=delete_source,
    )
    if isinstance(result, tuple):
        return jsonify({"status": "failed", "reason": result[1]}), 400
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
    user = current_user
    user_id = request.args.get("user_id")
    if user_id is not None:
        if not current_user.is_admin():
            return jsonify({"status": "failed", "reason": "admin only"}), 403
        user = User.query.filter_by(id=int(user_id)).one_or_none()
        if user is None:
            return jsonify({"status": "failed", "reason": "user not found"}), 404
    result = list_user_jobs(
        user,
        query,
        page=request.args.get("page", 1),
        per_page=request.args.get("per_page", 25),
    )
    return jsonify({"status": "successful", **result})


@api_v1_bp.route("/admin/users", methods=["GET"])
@api_login_required
def list_users_admin():
    if not current_user.is_admin():
        return jsonify({"status": "failed", "reason": "admin only"}), 403
    users = User.query.order_by(User.username).all()
    return jsonify(
        {
            "status": "successful",
            "users": [{"id": u.id, "username": u.username} for u in users],
        }
    )


@api_v1_bp.route("/jobs/<job_id>/reusable-files", methods=["GET"])
@api_login_required
def reusable_files(job_id: str):
    job = accessible_job(job_id)
    return jsonify({"status": "successful", **list_reusable_files(job)})


@api_v1_bp.route("/jobs/<job_id>", methods=["GET"])
@api_login_required
def get_job(job_id: str):
    body, status = get_job_status_payload(current_user, job_id)
    return jsonify(body), status


@api_v1_bp.route("/jobs/<job_id>/status", methods=["GET"])
@api_login_required
def get_job_status(job_id: str):
    """Thin status poll (replaces legacy /api/dag/.../run/...)."""
    job = Job.query.filter_by(job_id=job_id).one_or_none()
    if job is None or (job.user_id != current_user.id and not current_user.is_admin()):
        abort(404)

    try:
        sync_job_status_from_prefect(job)
    except Exception:
        pass

    return jsonify(
        {
            "state": (job.status or "unknown").lower(),
            "job_id": job_id,
            "dag_run_id": job_id,
            "flow_run_id": job.prefect_flow_run_id,
        }
    )


@api_v1_bp.route("/jobs/<job_id>", methods=["PATCH"])
@api_login_required
def patch_job(job_id: str):
    data = request.get_json(silent=True) or {}
    if "name" not in data:
        return jsonify({"status": "failed", "reason": "name field required"}), 400
    body, status = rename_job(current_user, job_id, data.get("name"))
    return jsonify(body), status


@api_v1_bp.route("/jobs/<job_id>", methods=["DELETE"])
@api_login_required
def remove_job(job_id: str):
    body, status = delete_job(current_user, job_id)
    return jsonify(body), status


@api_v1_bp.route("/jobs/<job_id>/retry", methods=["POST"])
@api_login_required
def retry_job_route(job_id: str):
    data = request.get_json(silent=True) or {}
    force = bool(data.get("force") or request.args.get("force"))
    body, status = retry_job(current_user, job_id, force=force)
    return jsonify(body), status
