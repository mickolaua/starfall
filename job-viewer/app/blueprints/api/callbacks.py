from flask import Blueprint, jsonify, request

from ...extensions import db
from ...models import Job
from ...models.job import apply_job_status
from ...services.auth import require_callback_token

callbacks_bp = Blueprint("callbacks", __name__)


@callbacks_bp.route("/api/jobs/update/<job_id>", methods=["POST"])
def update_job(job_id: str):
    """
    Worker callback to update job status.
    Requires Authorization: Bearer <token> or X-JobViewer-Token header.
    """
    require_callback_token()
    data = request.get_json(silent=True) or {}
    job = Job.query.filter_by(job_id=job_id).one_or_none()
    if not job:
        return (
            jsonify({"status": "fail", "reason": f"job with job_id={job_id} not found"}),
            404,
        )
    if data.get("status", ""):
        apply_job_status(job, data["status"])
        db.session.commit()
    else:
        return (
            jsonify(
                {"status": "fail", "reason": f"status for job_id={job_id} not fetched"}
            ),
            400,
        )
    return jsonify({"status": "success"})


@callbacks_bp.route("/api/internal/job-complete", methods=["POST"])
def job_complete():
    """Worker callback: mark a single job successful. Requires callback token."""
    require_callback_token()
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"status": "fail", "reason": "job_id required"}), 400

    job = Job.query.filter_by(job_id=job_id).one_or_none()
    if not job:
        return (
            jsonify({"status": "fail", "reason": f"job with job_id={job_id} not found"}),
            404,
        )

    apply_job_status(job, data.get("status") or "SUCCESS")
    db.session.commit()
    return jsonify({"status": "received"}), 200
