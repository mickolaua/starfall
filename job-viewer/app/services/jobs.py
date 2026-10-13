from pathlib import Path

from flask import abort, current_app
from flask_login import current_user

from ..constants import (
    INPUT_SUBDIRS,
    PREVIEW_EXTENSIONS,
    STACK_PRODUCT_MARKERS,
)
from ..extensions import db
from ..models import Job
from .prefect import get_prefect_flow_run_by_idempotency_key


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
) -> tuple[str, list[str], list[str], list[str]] | tuple[None, str]:
    """Ensure working_dir and file paths stay under RESULT_FOLDER/<user_id>/<subid>."""
    subid = data.get("subid") or ""
    if not subid or "/" in subid or "\\" in subid or ".." in subid:
        return None, "invalid job id"

    user_root = (Path(current_app.config["RESULT_FOLDER"]) / str(current_user.id)).resolve()
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
        from .prefect import extract_state_type, standardize_status

        job.status = standardize_status(extract_state_type(flow_run.get("state")))
        db.session.commit()
