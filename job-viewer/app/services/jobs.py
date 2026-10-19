import math
import os
import shutil
from datetime import datetime, timezone
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
    cancel_prefect_flow_run,
    extract_state_type,
    get_latest_prefect_flow_run_for_job,
    get_prefect_flow_run_by_id,
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
    if job is None:
        abort(404)
    return job


def accessible_job(job_id: str) -> Job:
    """Owner or admin may access the job."""
    job = Job.query.filter_by(job_id=job_id).one_or_none()
    if job is None:
        abort(404)
    if job.user_id != current_user.id and not current_user.is_admin():
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
    """Ensure working_dir is the job folder; frame paths may be anywhere under the owner's user root."""
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
            if path.is_symlink() or not path.is_file():
                return None
            if not path.is_relative_to(user_root):
                return None
            resolved.append(str(path))
        return resolved

    lights = _check_list("light_filenames")
    darks = _check_list("dark_filenames")
    flats = _check_list("flat_filenames")
    if lights is None or darks is None or flats is None:
        return None, "one or more file paths are outside your result folder"
    if not lights:
        return None, "no light images"
    return str(working_dir), lights, darks, flats


def sync_job_status_from_prefect(job: Job) -> None:
    """Refresh Job.status from the current Prefect flow run when one exists."""
    flow_run = None
    if job.prefect_flow_run_id:
        flow_run = get_prefect_flow_run_by_id(job.prefect_flow_run_id)
    if flow_run is None and job.prefect_idempotency_key:
        flow_run = get_prefect_flow_run_by_idempotency_key(job.prefect_idempotency_key)
    if flow_run is None:
        flow_run = get_latest_prefect_flow_run_for_job(job.job_id)
    if flow_run is None:
        flow_run = get_prefect_flow_run_by_idempotency_key(job.job_id)
    if not flow_run:
        return

    apply_job_status(job, extract_state_type(flow_run.get("state")))
    run_id = flow_run.get("id")
    if run_id:
        job.prefect_flow_run_id = run_id
    idem = flow_run.get("idempotency_key")
    if idem:
        job.prefect_idempotency_key = idem
    elif not job.prefect_idempotency_key:
        job.prefect_idempotency_key = job.job_id
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


def _role_hint_for_relative(relative_name: str) -> str:
    lower = relative_name.lower().replace("\\", "/")
    if lower.startswith("lights/") or lower.startswith("light/"):
        return "light"
    if lower.startswith("darks/") or lower.startswith("dark/"):
        return "dark"
    if lower.startswith("flats/") or lower.startswith("flat/"):
        return "flat"
    if is_stacked_product(relative_name) or is_calibrated_image(relative_name):
        return "product"
    return "other"


def list_reusable_files(job: Job) -> dict:
    job_directory = job_result_directory(job)
    if not job_directory.is_dir():
        return {"files": []}

    files = []
    for artifact in job_directory.rglob("*"):
        if artifact.is_symlink() or not artifact.is_file():
            continue
        resolved = artifact.resolve()
        if not resolved.is_relative_to(job_directory):
            continue
        ext = artifact.suffix.lower().lstrip(".")
        if ext not in _UPLOAD_EXTENSIONS:
            continue
        relative = artifact.relative_to(job_directory).as_posix()
        files.append(
            {
                "path": relative,
                "name": artifact.name,
                "role_hint": _role_hint_for_relative(relative),
                "size": artifact.stat().st_size,
            }
        )
    files.sort(key=lambda item: item["path"].lower())
    return {"files": files}


def _hardlink_or_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def _unique_dest(dest_dir: Path, filename: str) -> Path:
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    n = 1
    while True:
        candidate = dest_dir / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def create_job_shell(user: User) -> dict:
    """Create empty job dirs for reference-mode submit."""
    job_id = uuid4().hex
    outdir = Path(current_app.config["RESULT_FOLDER"]) / str(user.id) / job_id
    for sub in ("lights", "darks", "flats"):
        (outdir / sub).mkdir(parents=True, exist_ok=True)
    return {
        "status": "successful",
        "working_dir": str(outdir.resolve()),
        "subid": job_id,
        "light_filenames": [],
        "dark_filenames": [],
        "flat_filenames": [],
    }


def attach_reused_frames(
    user: User,
    items: list[dict],
    *,
    mode: str = "copy",
    delete_source: bool = False,
) -> dict | tuple[None, str]:
    """
    Build a new job from prior-job files.
    mode=copy: hardlink/copy into new job role dirs.
    mode=reference: create shell + return abs source paths (same owner only).
    """
    if not items:
        return None, "no files selected"
    mode = (mode or "copy").lower().strip()
    if mode not in {"copy", "reference"}:
        return None, "invalid mode"

    role_lists: dict[str, list[str]] = {"light": [], "dark": [], "flat": []}
    pending_deletes: list[Path] = []

    if mode == "reference":
        shell = create_job_shell(user)
        working_dir = shell["working_dir"]
        job_id = shell["subid"]
    else:
        job_id = uuid4().hex
        working_dir = str(
            (Path(current_app.config["RESULT_FOLDER"]) / str(user.id) / job_id).resolve()
        )
        for sub in ("lights", "darks", "flats"):
            Path(working_dir, sub).mkdir(parents=True, exist_ok=True)

    role_dir = {
        "light": Path(working_dir) / "lights",
        "dark": Path(working_dir) / "darks",
        "flat": Path(working_dir) / "flats",
    }

    for raw in items:
        from_job_id = (raw.get("from_job_id") or "").strip()
        relative_path = (raw.get("relative_path") or "").strip().replace("\\", "/")
        role = (raw.get("role") or "").strip().lower()
        if role not in role_lists:
            return None, f"invalid role: {role}"
        if not from_job_id or not relative_path or ".." in relative_path.split("/"):
            return None, "invalid reuse item"

        source_job = Job.query.filter_by(job_id=from_job_id).one_or_none()
        if source_job is None:
            return None, f"source job not found: {from_job_id}"
        if source_job.user_id != user.id and not current_user.is_admin():
            return None, "not allowed to reuse that job"
        if mode == "reference" and source_job.user_id != user.id:
            return None, "reference mode only allowed for your own jobs"

        source_root = job_result_directory(source_job)
        src = (source_root / relative_path).resolve()
        if src.is_symlink() or not src.is_file() or not src.is_relative_to(source_root):
            return None, f"invalid source file: {relative_path}"

        ext = src.suffix.lower().lstrip(".")
        if ext not in _UPLOAD_EXTENSIONS:
            return None, f"unsupported file type: {src.name}"

        if mode == "copy":
            dest = _unique_dest(role_dir[role], secure_filename(src.name) or src.name)
            _hardlink_or_copy(src, dest)
            role_lists[role].append(str(dest.resolve()))
            if delete_source:
                pending_deletes.append(src)
        else:
            role_lists[role].append(str(src))

    if not role_lists["light"]:
        return None, "no light images"

    if delete_source and mode == "copy":
        result_root = Path(current_app.config["RESULT_FOLDER"]).resolve()
        for src in pending_deletes:
            try:
                if src.is_file() and src.is_relative_to(result_root):
                    src.unlink()
                    current_app.logger.info("Deleted reuse source file %s", src)
            except OSError as exc:
                current_app.logger.error("Failed to delete source %s: %s", src, exc)

    return {
        "status": "successful",
        "working_dir": working_dir,
        "subid": job_id,
        "light_filenames": role_lists["light"],
        "dark_filenames": role_lists["dark"],
        "flat_filenames": role_lists["flat"],
        "mode": mode,
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
            prefect_idempotency_key=data["subid"],
            prefect_flow_run_id=json_resp.get("id"),
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

    _list_sync = frozenset(
        {"RUNNING", "QUEUED", "PENDING", "running", "queued", "pending"}
    )
    for job in jobs:
        if job.status in _list_sync or job.finished_at is None:
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
    job = Job.query.filter_by(job_id=job_id).one_or_none()
    if job is None or (job.user_id != user.id and not user.is_admin()):
        return {"status": "failed", "reason": "job not found"}, 404

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
        "prefect_idempotency_key": job.prefect_idempotency_key,
        "prefect_flow_run_id": job.prefect_flow_run_id,
    }, 200


def rename_job(user: User, job_id: str, name) -> tuple[dict, int]:
    job = Job.query.filter_by(job_id=job_id).one_or_none()
    if job is None:
        return {"status": "failed", "reason": "job not found"}, 404
    if job.user_id != user.id and not user.is_admin():
        return {"status": "failed", "reason": "job not found"}, 404
    job.name = normalize_job_name(name)
    db.session.commit()
    return {
        "status": "successful",
        "subid": job.job_id,
        "name": job.name,
    }, 200


_ACTIVE_STATUSES = frozenset(
    {"RUNNING", "QUEUED", "PENDING", "running", "queued", "pending", "UNKNOWN"}
)


def _prune_derived_products(working_dir: Path, stack_mode: str | None) -> None:
    patterns = [
        "*calibrated*",
        "good_frames.txt",
        "*.log",
        "*.proclog",
    ]
    if stack_mode and stack_mode != "none":
        patterns.append(f"*-{stack_mode}.fit")
        patterns.append(f"*.calibrated.*-{stack_mode}.fit")
    for pattern in patterns:
        for path in working_dir.glob(pattern):
            if path.is_file() and not path.is_symlink():
                try:
                    path.unlink()
                except OSError as exc:
                    current_app.logger.error("Failed to prune %s: %s", path, exc)
        for path in working_dir.rglob(pattern):
            # Skip input role trees for calibrated beside lights — plan says prune calibrated
            if path.is_file() and not path.is_symlink():
                rel = path.relative_to(working_dir).as_posix().lower()
                # Keep original uploads in lights/darks/flats that are not calibrated products
                if any(rel.startswith(p) for p in ("lights/", "darks/", "flats/", "light/", "dark/", "flat/")):
                    if "calibrated" not in path.name.lower():
                        continue
                try:
                    path.unlink()
                except OSError as exc:
                    current_app.logger.error("Failed to prune %s: %s", path, exc)


def delete_job(user: User, job_id: str) -> tuple[dict, int]:
    job = Job.query.filter_by(job_id=job_id).one_or_none()
    if job is None:
        return {"status": "failed", "reason": "job not found"}, 404
    if job.user_id != user.id and not user.is_admin():
        return {"status": "failed", "reason": "job not found"}, 404

    if job.status in _ACTIVE_STATUSES:
        cancel_id = job.prefect_flow_run_id
        if not cancel_id:
            flow_run = get_latest_prefect_flow_run_for_job(job.job_id)
            cancel_id = flow_run.get("id") if flow_run else None
        if cancel_id:
            try:
                cancel_prefect_flow_run(cancel_id)
            except Exception as exc:
                current_app.logger.error(
                    "Failed to cancel Prefect run for %s: %s", job.job_id, exc
                )

    job_dir = job_result_directory(job)
    user_root = (Path(current_app.config["RESULT_FOLDER"]) / str(job.user_id)).resolve()
    if job_dir.is_dir() and job_dir.is_relative_to(user_root):
        shutil.rmtree(job_dir)

    db.session.delete(job)
    db.session.commit()
    return {"status": "successful", "subid": job_id}, 200


def retry_job(user: User, job_id: str, *, force: bool = False) -> tuple[dict, int]:
    job = Job.query.filter_by(job_id=job_id).one_or_none()
    if job is None:
        return {"status": "failed", "reason": "job not found"}, 404
    if job.user_id != user.id and not user.is_admin():
        return {"status": "failed", "reason": "job not found"}, 404

    status_upper = (job.status or "").upper()
    if status_upper in {"RUNNING", "QUEUED", "PENDING"}:
        return {"status": "failed", "reason": "job is still active"}, 400
    if status_upper == "SUCCESS" and not force:
        return {
            "status": "failed",
            "reason": "job succeeded; pass force=true to re-run",
        }, 400
    if status_upper not in {"FAILED", "SUCCESS", "UNKNOWN", "CRASHED"} and not force:
        return {"status": "failed", "reason": "job is not in a retryable state"}, 400

    params = job.get_job_parameters() or {}
    if not params.get("working_dir") or not params.get("light_filenames"):
        return {"status": "failed", "reason": "job has no stored parameters to retry"}, 400

    owner = db.session.get(User, job.user_id) or user
    validated = validate_submit_paths(
        {
            "subid": job.job_id,
            "working_dir": params["working_dir"],
            "light_filenames": params.get("light_filenames") or [],
            "dark_filenames": params.get("dark_filenames") or [],
            "flat_filenames": params.get("flat_filenames") or [],
        },
        user=owner,
    )
    if validated[0] is None:
        return {"status": "failed", "reason": validated[1]}, 400

    working_dir, lights, darks, flats = validated
    params = {**params, "working_dir": working_dir, "light_filenames": lights,
              "dark_filenames": darks, "flat_filenames": flats}

    wd = Path(working_dir)
    _prune_derived_products(wd, job.stack_mode or params.get("stack_mode"))

    deployment_id = resolve_prefect_deployment_id()
    if not deployment_id:
        return {"status": "failed", "reason": "Prefect deployment not found"}, 500

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    idem = f"{job.job_id}-retry-{ts}"
    response = requests.post(
        prefect_url(f"/deployments/{deployment_id}/create_flow_run"),
        headers=prefect_headers(),
        json={
            "name": idem,
            "idempotency_key": idem,
            "parameters": params,
        },
        timeout=30,
    )
    try:
        json_resp = response.json()
    except ValueError:
        json_resp = {"raw": response.text}

    if response.status_code not in (200, 201):
        return {"status": "failed", "reason": json_resp}, 500

    state_type = extract_state_type(json_resp.get("state"))
    job.prefect_idempotency_key = idem
    job.prefect_flow_run_id = json_resp.get("id")
    job.set_job_parameters(params)
    apply_job_status(job, state_type or "PENDING")
    db.session.commit()
    return {
        "status": "successful",
        "subid": job.job_id,
        "job_status": job.status,
        "idempotency_key": idem,
        "prefect_flow_run_id": job.prefect_flow_run_id,
    }, 200
