import math
import os
from pathlib import Path
from uuid import uuid4

import requests
from flask import abort, current_app
from flask_login import current_user
from sqlalchemy import or_
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from ..constants import (
    INPUT_SUBDIRS,
    PREVIEW_EXTENSIONS,
    STACK_PRODUCT_MARKERS,
)
from ..extensions import db
from ..models import Job, User
from ..models.job import apply_job_status
from .prefect import (
    extract_state_type,
    get_prefect_flow_run_by_idempotency_key,
    prefect_headers,
    prefect_url,
    resolve_prefect_deployment_id,
    standardize_status,
)

_DEFAULT_PER_PAGE = 25
_MAX_PER_PAGE = 100


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


_JOB_NAME_MAX_LEN = 200


def normalize_job_name(value) -> str | None:
    """Optional display name: strip, truncate to 200; empty → None."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    name = value.strip()
    if not name:
        return None
    return name[:_JOB_NAME_MAX_LEN]

_UPLOAD_EXTENSIONS = frozenset(
    {"fit", "fits", "fts", "zip", "7z", "gz", "tar", "rar"}
)


def owned_job(job_id: str) -> Job:
    job = Job.query.filter_by(job_id=job_id, user_id=current_user.id).one_or_none()
    print(job)
    if job is None:
        abort(404)
    return job


def job_result_directory(job: Job) -> Path:
    user_directory = (Path(current_app.config["RESULT_FOLDER"]) / str(job.user_id)).resolve()
    job_directory = (user_directory / job.job_id).resolve()
    if not job_directory.is_relative_to(user_directory):
        abort(404)
    return job_directory


def resolve_job_artifact(job: Job, filename: str) -> Path:
    job_directory = job_result_directory(job)
    artifact = job_directory / filename
    if artifact.is_symlink():
        abort(404)
    artifact = artifact.resolve()
    if not artifact.is_relative_to(job_directory) or not artifact.is_file():
        abort(404)
    return artifact


def resolve_stack_mode(job: Job) -> str | None:
    if job.stack_mode:
        return job.stack_mode
    stored = job.get_job_parameters() or {}
    if stored.get("stack_mode"):
        return stored.get("stack_mode")
    try:
        flow_run = get_prefect_flow_run_by_idempotency_key(job.job_id)
        if flow_run:
            params = flow_run.get("parameters") or {}
            mode = params.get("stack_mode")
            if mode:
                return mode
            options = params.get("options") or {}
            return options.get("stack_mode")
    except Exception as exc:
        current_app.logger.error(
            "Failed to resolve stack_mode for job %s: %s", job.job_id, exc
        )
    return None


def is_previewable_image(relative_name: str) -> bool:
    return Path(relative_name).suffix.lower() in PREVIEW_EXTENSIONS


def is_stacked_product(relative_name: str) -> bool:
    name = relative_name.lower()
    if any(name.startswith(prefix) for prefix in INPUT_SUBDIRS):
        return False
    if "/" in relative_name:
        return False
    return any(marker in name for marker in STACK_PRODUCT_MARKERS)


def is_calibrated_image(relative_name: str) -> bool:
    return (
        is_previewable_image(relative_name)
        and "calibrated" in Path(relative_name).name.lower()
    )


def categorize_artifact(
    relative_name: str, stack_mode: str | None, has_stacked_root: bool
) -> str:
    suffix = Path(relative_name).suffix.lower()
    name_lower = relative_name.lower()

    if is_previewable_image(relative_name):
        if is_stacked_product(relative_name):
            return "processed_image"
        if (stack_mode or "").lower() == "none" and is_calibrated_image(relative_name):
            return "processed_image"
        if not stack_mode and not has_stacked_root and is_calibrated_image(relative_name):
            return "processed_image"
        return "other"

    if suffix == ".json":
        return "json"
    if suffix in {".log", ".proclog", ".txt"}:
        return "log"
    if suffix == ".reg" or name_lower.endswith(".reg"):
        return "region"
    return "other"


def validate_submit_paths(
    data: dict,
    user: User | None = None,
) -> tuple[str, list[str], list[str], list[str]] | tuple[None, str]:
    """Ensure working_dir and file paths stay under RESULT_FOLDER/<user_id>/<subid>."""
    subid = data.get("subid") or ""
    if not subid or "/" in subid or "\\" in subid or ".." in subid:
        return None, "invalid job id"

    owner = user or current_user
    user_root = (Path(current_app.config["RESULT_FOLDER"]) / str(owner.id)).resolve()
    expected_wd = (user_root / subid).resolve()
    try:
        working_dir = Path(data["working_dir"]).resolve()
    except (KeyError, TypeError, OSError):
        return None, "invalid working_dir"

    if working_dir != expected_wd or not working_dir.is_relative_to(user_root):
        return None, "working_dir is outside your result folder"

    def _check_list(key: str) -> list[str] | None:
        values = data.get(key) or []
        if not isinstance(values, list):
            return None
        resolved = []
        for item in values:
            try:
                path = Path(item).resolve()
            except (TypeError, OSError):
                return None
            if not path.is_relative_to(working_dir):
                return None
            resolved.append(str(path))
        return resolved

    lights = _check_list("light_filenames")
    darks = _check_list("dark_filenames")
    flats = _check_list("flat_filenames")
    if lights is None or darks is None or flats is None:
        return None, "one or more file paths are outside the job folder"
    return str(working_dir), lights, darks, flats


def sync_job_status_from_prefect(job: Job) -> None:
    flow_run = get_prefect_flow_run_by_idempotency_key(job.job_id)
    if flow_run:
        apply_job_status(job, extract_state_type(flow_run.get("state")))
        db.session.commit()


def _store_file_list(file_list: list[FileStorage], out_dir: str) -> list[str]:
    filenames = []
    for file in file_list:
        if not file or not file.filename:
            continue
        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext not in _UPLOAD_EXTENSIONS:
            continue
        filename = secure_filename(file.filename)
        os.makedirs(out_dir, exist_ok=True)
        outpath = os.path.join(out_dir, filename)
        file.save(outpath)
        filenames.append(outpath)
    return filenames


def store_uploaded_frames(
    user: User,
    lights: list[FileStorage],
    darks: list[FileStorage] | None = None,
    flats: list[FileStorage] | None = None,
) -> dict | tuple[None, str]:
    """Save multipart frames under RESULT_FOLDER/<user_id>/<subid>/{lights,darks,flats}."""
    if not lights:
        return None, "no light images"

    job_id = uuid4().hex
    outdir = os.path.join(
        current_app.config["RESULT_FOLDER"], str(user.id), str(job_id)
    )
    light_dir = os.path.realpath(os.path.join(outdir, "lights"))
    dark_dir = os.path.realpath(os.path.join(outdir, "darks"))
    flat_dir = os.path.realpath(os.path.join(outdir, "flats"))

    light_filenames = _store_file_list(lights, light_dir)
    if not light_filenames:
        return None, "no valid light images"

    return {
        "status": "successful",
        "working_dir": outdir,
        "subid": job_id,
        "light_filenames": light_filenames,
        "dark_filenames": _store_file_list(darks or [], dark_dir),
        "flat_filenames": _store_file_list(flats or [], flat_dir),
    }


def _format_transient_circle(transient_circle) -> str:
    if isinstance(transient_circle, dict):
        return (
            f"{transient_circle.get('ra', '0')},"
            f"{transient_circle.get('dec', '0')},"
            f"{transient_circle.get('radius', '10')}"
        )
    return transient_circle


def create_prefect_job(user: User, data: dict) -> tuple[dict, int]:
    """
    Validate paths, create Prefect flow run, persist Job row.
    Returns (json_body, http_status).
    """
    validated = validate_submit_paths(data, user=user)
    if validated[0] is None:
        return (
            {"status": "failed", "subid": data.get("subid"), "reason": validated[1]},
            400,
        )
    working_dir, light_filenames, dark_filenames, flat_filenames = validated

    apex_conf = data.get("apex_conf", "default")
    astrometric_catalog = data.get("astrometric_catalog", "gaia")
    circle_str = _format_transient_circle(data.get("transient_circle", {}))
    ra_field = data.get("ra_field")
    dec_field = data.get("dec_field")

    deployment_id = resolve_prefect_deployment_id()
    if not deployment_id:
        return (
            {
                "status": "failed",
                "subid": data.get("subid"),
                "reason": "Prefect deployment not found",
            },
            500,
        )

    # Task input only — never include lifecycle status in this dict.
    parameters = {
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
    }

    response = requests.post(
        prefect_url(f"/deployments/{deployment_id}/create_flow_run"),
        headers=prefect_headers(),
        json={
            "name": data["subid"],
            "idempotency_key": data["subid"],
            "parameters": parameters,
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
            user_id=user.id,
            job_id=data["subid"],
            name=normalize_job_name(data.get("name")),
            status=standardize_status(state_type or "PENDING"),
            stack_mode=data.get("stack_mode"),
        )
        job.set_job_parameters(parameters)
        apply_job_status(job, state_type or "PENDING")
        db.session.add(job)
        db.session.commit()
        return {
            "status": "successful",
            "subid": data["subid"],
            "name": job.name,
        }, 200

    return (
        {"status": "failed", "subid": data.get("subid"), "reason": json_resp},
        500,
    )


def list_user_jobs(
    user: User,
    query: str = "",
    *,
    page: int = 1,
    per_page: int = _DEFAULT_PER_PAGE,
) -> dict:
    """Return a newest-first page of the user's jobs plus pagination metadata."""
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(per_page)
    except (TypeError, ValueError):
        per_page = _DEFAULT_PER_PAGE

    page = max(page, 1)
    per_page = min(max(per_page, 1), _MAX_PER_PAGE)

    base = Job.query.filter_by(user_id=user.id)
    if query:
        pattern = f"%{query}%"
        base = base.filter(
            or_(Job.job_id.ilike(pattern), Job.name.ilike(pattern))
        )

    total = base.count()
    pages = math.ceil(total / per_page) if total else 0
    if pages and page > pages:
        page = pages

    jobs = (
        base.order_by(Job.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    for job in jobs:
        if job.status in {"RUNNING", "QUEUED", "running", "queued"}:
            try:
                sync_job_status_from_prefect(job)
            except Exception as exc:
                current_app.logger.error(
                    "Failed to sync job %s: %s", job.job_id, exc
                )

    return {
        "submissions": [
            {
                "subid": job.job_id,
                "name": job.name,
                "status": job.status,
                "stack_mode": job.stack_mode,
                "started_at": _iso(job.started_at),
                "finished_at": _iso(job.finished_at),
            }
            for job in jobs
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


def get_job_status_payload(user: User, job_id: str) -> tuple[dict, int]:
    job = Job.query.filter_by(job_id=job_id, user_id=user.id).one_or_none()
    if job is None:
        return {"status": "failed", "reason": "job not found"}, 404

    if job.status in {"RUNNING", "QUEUED", "running", "queued"}:
        try:
            sync_job_status_from_prefect(job)
        except Exception as exc:
            current_app.logger.error("Failed to sync job %s: %s", job.job_id, exc)

    return {
        "status": "successful",
        "subid": job.job_id,
        "name": job.name,
        "job_status": job.status,
        "stack_mode": job.stack_mode,
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "parameters": job.get_job_parameters(),
    }, 200


def rename_job(user: User, job_id: str, name) -> tuple[dict, int]:
    job = Job.query.filter_by(job_id=job_id, user_id=user.id).one_or_none()
    if job is None:
        return {"status": "failed", "reason": "job not found"}, 404
    job.name = normalize_job_name(name)
    db.session.commit()
    return {
        "status": "successful",
        "subid": job.job_id,
        "name": job.name,
    }, 200
