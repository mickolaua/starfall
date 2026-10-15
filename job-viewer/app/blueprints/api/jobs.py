from io import BytesIO
from pathlib import Path

from astropy.io import fits
from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    request,
    send_file,
    send_from_directory,
)
from fits_viewer import (
    discover_reg_files,
    fits_header_payload,
    fits_preview_png,
    normalize_reg_content,
    normalize_structured_region,
)

from ...compat import url_for
from ...constants import TEXT_PREVIEW_EXTENSIONS, TEXT_PREVIEW_MAX_BYTES
from ...services.auth import api_login_required
from ...services.jobs import (
    categorize_artifact,
    is_previewable_image,
    is_stacked_product,
    job_result_directory,
    owned_job,
    resolve_job_artifact,
    resolve_stack_mode,
)

api_jobs_bp = Blueprint("api_jobs", __name__, url_prefix="/api/jobs")


@api_jobs_bp.route("/<job_id>/raw/<path:filename>", methods=["GET"])
@api_login_required
def get_job_raw(job_id: str, filename: str):
    job = owned_job(job_id)
    artifact = resolve_job_artifact(job, filename)
    return send_from_directory(artifact.parent, artifact.name, as_attachment=False)


@api_jobs_bp.route("/<job_id>/regions/<path:filename>", methods=["GET"])
@api_login_required
def get_job_regions(job_id: str, filename: str):
    job = owned_job(job_id)
    if not filename.endswith(".reg"):
        abort(400)

    artifact = resolve_job_artifact(job, filename)

    try:
        with open(artifact, "r") as f:
            content = f.read()
        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_jobs_bp.route("/<job_id>/results", methods=["GET"])
@api_login_required
def get_job_results(job_id: str):
    job = owned_job(job_id)
    job_directory = job_result_directory(job)
    if not job_directory.is_dir():
        return jsonify({"files": [], "truncated": False, "stack_mode": job.stack_mode})

    stack_mode = resolve_stack_mode(job)
    relative_paths = []
    for artifact in job_directory.rglob("*"):
        if artifact.is_symlink() or not artifact.is_file():
            continue
        resolved = artifact.resolve()
        if not resolved.is_relative_to(job_directory):
            continue
        relative_paths.append(artifact.relative_to(job_directory).as_posix())

    has_stacked_root = any(is_stacked_product(name) for name in relative_paths)

    artifacts = []
    for relative_name in relative_paths:
        artifact = job_directory / relative_name
        category = categorize_artifact(relative_name, stack_mode, has_stacked_root)
        item = {
            "name": relative_name,
            "size": artifact.stat().st_size,
            "category": category,
            "download_url": url_for(
                "download_job_result", job_id=job.job_id, filename=relative_name
            ),
        }

        if is_previewable_image(relative_name):
            item["preview_url"] = url_for(
                "preview_job_result", job_id=job.job_id, filename=relative_name
            )
            reg_path = artifact.with_suffix(".reg")
            if reg_path.exists():
                item["reg_url"] = url_for(
                    "get_job_regions",
                    job_id=job.job_id,
                    filename=reg_path.relative_to(job_directory).as_posix(),
                )
            try:
                if artifact.suffix.lower() in {".fit", ".fits", ".fts"}:
                    with fits.open(artifact) as hdul:
                        header = hdul[0].header
                        item["original_dimensions"] = {
                            "width": header.get("NAXIS1", 0),
                            "height": header.get("NAXIS2", 0),
                        }
                else:
                    item["original_dimensions"] = None
            except Exception:
                item["original_dimensions"] = None

        if Path(relative_name).suffix.lower() in TEXT_PREVIEW_EXTENSIONS:
            item["text_preview_url"] = url_for(
                "get_job_text_preview", job_id=job.job_id, filename=relative_name
            )

        artifacts.append(item)

    artifacts.sort(key=lambda item: item["name"].lower())
    return jsonify(
        {
            "files": artifacts[:200],
            "truncated": len(artifacts) > 200,
            "stack_mode": stack_mode,
        }
    )


@api_jobs_bp.route("/<job_id>/text/<path:filename>", methods=["GET"])
@api_login_required
def get_job_text_preview(job_id: str, filename: str):
    job = owned_job(job_id)
    suffix = Path(filename).suffix.lower()
    if suffix not in TEXT_PREVIEW_EXTENSIONS:
        abort(400)

    artifact = resolve_job_artifact(job, filename)
    size = artifact.stat().st_size
    truncated = size > TEXT_PREVIEW_MAX_BYTES
    raw = artifact.read_bytes()[:TEXT_PREVIEW_MAX_BYTES]
    preview_bytes = len(raw)
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("utf-8", errors="replace")

    if suffix == ".json":
        try:
            import json as json_lib

            content = json_lib.dumps(
                json_lib.loads(content), indent=2, ensure_ascii=False
            )
        except (ValueError, TypeError):
            pass

    return jsonify(
        {
            "name": filename,
            "content": content,
            "truncated": truncated,
            "preview_bytes": preview_bytes,
            "size": size,
        }
    )


@api_jobs_bp.route("/<job_id>/results/<path:filename>", methods=["GET"])
@api_login_required
def download_job_result(job_id: str, filename: str):
    job = owned_job(job_id)
    artifact = resolve_job_artifact(job, filename)
    return send_from_directory(
        artifact.parent, artifact.name, as_attachment=True, download_name=artifact.name
    )


@api_jobs_bp.route("/<job_id>/preview/<path:filename>", methods=["GET"])
@api_login_required
def preview_job_result(job_id: str, filename: str):
    job = owned_job(job_id)
    artifact = resolve_job_artifact(job, filename)
    scale = request.args.get("scale", "linear")
    colormap = request.args.get("colormap", "gray")
    if artifact.suffix.lower() in {".fit", ".fits", ".fts"}:
        try:
            preview = fits_preview_png(artifact, scale=scale, colormap=colormap)
        except (OSError, TypeError, ValueError):
            return jsonify({"error": "This FITS file could not be previewed."}), 422
        return send_file(BytesIO(preview), mimetype="image/png")
    if artifact.suffix.lower() not in {
        ".bmp",
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".webp",
    }:
        abort(404)
    return send_file(artifact, as_attachment=False)


@api_jobs_bp.route("/<job_id>/header/<path:filename>", methods=["GET"])
@api_login_required
def get_job_fits_header(job_id: str, filename: str):
    job = owned_job(job_id)
    artifact = resolve_job_artifact(job, filename)
    if artifact.suffix.lower() not in {".fit", ".fits", ".fts"}:
        return jsonify({"error": "header is only available for FITS images"}), 400
    try:
        return jsonify(fits_header_payload(artifact))
    except Exception as exc:
        current_app.logger.error("Failed to read FITS header for %s: %s", filename, exc)
        return jsonify({"error": "failed to read FITS header"}), 500


@api_jobs_bp.route("/<job_id>/overlay/parse/<path:filename>", methods=["POST"])
@api_login_required
def parse_job_overlay(job_id: str, filename: str):
    job = owned_job(job_id)
    artifact = resolve_job_artifact(job, filename)
    if artifact.suffix.lower() not in {".fit", ".fits", ".fts"}:
        return jsonify({"error": "overlays are only available for FITS images"}), 400

    data = request.get_json(silent=True) or {}
    try:
        if data.get("content"):
            layer = normalize_reg_content(
                data["content"],
                artifact,
                layer_name=data.get("name") or "uploaded.reg",
                default_color=data.get("color") or "lime",
            )
        else:
            coords = data.get("coords") or []
            layer = normalize_structured_region(
                artifact,
                shape=data.get("shape") or "circle",
                frame=data.get("frame") or "physical",
                coords=[str(c) for c in coords],
                color=data.get("color") or "cyan",
                text=data.get("text") or "",
                layer_name=data.get("name") or "Custom",
            )
        layer["source"] = "custom"
        return jsonify({"layer": layer})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        current_app.logger.error("overlay parse failed: %s", exc)
        return jsonify({"error": "failed to parse region"}), 500


@api_jobs_bp.route("/<job_id>/overlay/<path:filename>", methods=["GET"])
@api_login_required
def get_job_overlay(job_id: str, filename: str):
    job = owned_job(job_id)
    artifact = resolve_job_artifact(job, filename)
    if artifact.suffix.lower() not in {".fit", ".fits", ".fts"}:
        return jsonify(
            {"layers": [], "error": "overlays are only available for FITS images"}
        )

    layers = []
    for reg_path in discover_reg_files(artifact):
        try:
            content = reg_path.read_text(encoding="utf-8", errors="replace")
            layer = normalize_reg_content(
                content,
                artifact,
                layer_name=reg_path.name,
            )
            layer["source"] = "file"
            layer["path"] = reg_path.relative_to(job_result_directory(job)).as_posix()
            layers.append(layer)
        except Exception as exc:
            current_app.logger.error(
                "Failed to parse region file %s: %s", reg_path, exc
            )

    width = layers[0]["width"] if layers else 0
    height = layers[0]["height"] if layers else 0
    if not layers:
        try:
            from fits_viewer import fits_image_shape

            width, height = fits_image_shape(artifact)
        except Exception:
            pass

    return jsonify(
        {
            "width": width,
            "height": height,
            "flipped": True,
            "layers": layers,
        }
    )
