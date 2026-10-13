from datetime import datetime

import requests
from flask import Blueprint, abort, current_app, jsonify, request
from flask_login import current_user, login_required

from ...extensions import db
from ...models import Job, User
from ...services.jobs import sync_job_status_from_prefect, validate_submit_paths
from ...services.prefect import (
    extract_state_type,
    get_prefect_flow_run_by_idempotency_key,
    prefect_headers,
    prefect_url,
    resolve_prefect_deployment_id,
    standardize_status,
)

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
@login_required
def get_dag_run_details_ajax(dag_id: str, run_id: str):
    job = Job.query.filter_by(job_id=run_id, user_id=current_user.id).one_or_none()
    if job is None:
        abort(404)

    active_statuses = {"RUNNING", "QUEUED", "running", "queued"}
    if job.status in active_statuses:
        flow_run = get_prefect_flow_run_by_idempotency_key(run_id)
        if flow_run:
            state_type = extract_state_type(flow_run.get("state"))
            job.status = standardize_status(state_type)
            db.session.commit()
            dag_run_details = {
                "state": state_type.lower() if state_type else job.status.lower(),
                "dag_run_id": run_id,
                "flow_run_id": flow_run.get("id"),
            }
        else:
            dag_run_details = {"state": job.status.lower(), "dag_run_id": run_id}
    else:
        dag_run_details = {"state": job.status.lower(), "dag_run_id": run_id}

    return jsonify(dag_run_details)


@api_status_bp.route("/submit", methods=["POST"])
@login_required
def post_submit():
    data = request.json or {}

    validated = validate_submit_paths(data)
    if validated[0] is None:
        return (
            jsonify(
                {"status": "failed", "subid": data.get("subid"), "reason": validated[1]}
            ),
            400,
        )
    working_dir, light_filenames, dark_filenames, flat_filenames = validated

    apex_conf = data.get("apex_conf", "default")
    astrometric_catalog = data.get("astrometric_catalog", "gaia")
    transient_circle = data.get("transient_circle", {})

    ra_field = data.get("ra_field")
    dec_field = data.get("dec_field")

    if isinstance(transient_circle, dict):
        circle_str = (
            f"{transient_circle.get('ra', '0')},"
            f"{transient_circle.get('dec', '0')},"
            f"{transient_circle.get('radius', '10')}"
        )
    else:
        circle_str = transient_circle

    # Airflow (legacy) request body — kept for rollback parity with run_app.py
    _ = {
        "conf": {
            "working_dir": working_dir,
            "light_filenames": light_filenames,
            "dark_filenames": dark_filenames,
            "flat_filenames": flat_filenames,
            "apex_conf": apex_conf,
            "astrometric_catalog": astrometric_catalog,
            "transient_circle": circle_str,
            "telescope": data.get("telescope"),
            "stack_mode": data.get("stack_mode"),
            "group_frames": data.get("group_frames"),
            "group_frames_value": data.get("group_frames_value"),
            "band": data.get("filter"),
            "photometric_catalog": data.get("photometric_catalog"),
            "ra_field": ra_field,
            "dec_field": dec_field,
        },
        "dag_run_id": data["subid"],
        "logical_date": datetime.now().astimezone().isoformat(),
    }

    deployment_id = resolve_prefect_deployment_id()
    if not deployment_id:
        return (
            jsonify(
                {
                    "status": "failed",
                    "subid": data["subid"],
                    "reason": "Prefect deployment not found",
                }
            ),
            500,
        )

    response = requests.post(
        prefect_url(f"/deployments/{deployment_id}/create_flow_run"),
        headers=prefect_headers(),
        json={
            "name": data["subid"],
            "idempotency_key": data["subid"],
            "parameters": {
                "working_dir": working_dir,
                "light_filenames": light_filenames,
                "dark_filenames": dark_filenames,
                "flat_filenames": flat_filenames,
                "telescope": data.get("telescope"),
                "stack_mode": data.get("stack_mode"),
                "group_frames": data.get("group_frames"),
                "group_frames_value": data.get("group_frames_value"),
                "band": data.get("filter"),
                "astrometric_catalog": astrometric_catalog,
                "photometric_catalog": data.get("photometric_catalog"),
                "transient_circle": circle_str,
                "ra_field": ra_field,
                "dec_field": dec_field,
                "apex_conf": apex_conf,
            },
        },
        timeout=30,
    )

    try:
        json_resp = response.json()
    except ValueError:
        json_resp = {"raw": response.text}
    print(json_resp)

    if response.status_code in (200, 201):
        state_type = extract_state_type(json_resp.get("state"))
        job = Job(
            user_id=current_user.id,
            job_id=data["subid"],
            status=standardize_status(state_type or "PENDING"),
            stack_mode=data.get("stack_mode"),
        )
        db.session.add(job)
        db.session.commit()
        return jsonify({"status": "successful", "subid": data["subid"]})

    return (
        jsonify({"status": "failed", "subid": data["subid"], "reason": json_resp}),
        500,
    )


@api_status_bp.route("/user/<user_id>/submissions", methods=["GET"])
@login_required
def get_user_submitions_ajax(user_id: int):
    if int(user_id) != current_user.id and not current_user.is_admin():
        abort(403)

    user = User.query.filter_by(id=user_id).one_or_none()
    if not user:
        return jsonify({"status": "failed"})

    query_str = request.args.get("q", "").strip()

    all_jobs = user.jobs

    if query_str:
        filtered_jobs = [
            job for job in all_jobs if query_str.lower() in job.job_id.lower()
        ]
    else:
        filtered_jobs = all_jobs

    running_jobs = [
        job
        for job in filtered_jobs
        if job.status in ["RUNNING", "QUEUED", "running", "queued"]
    ]
    for job in running_jobs:
        try:
            sync_job_status_from_prefect(job)
        except Exception as e:
            current_app.logger.error(
                "Failed to proactively sync job %s: %s", job.job_id, e
            )

    jobs = [{"subid": job.job_id, "status": job.status} for job in filtered_jobs]

    return jsonify({"status": "successful", "submissions": jobs})
