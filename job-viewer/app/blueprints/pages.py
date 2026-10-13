import os
from pathlib import Path
from uuid import uuid4

import requests
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
)
from flask_login import current_user, login_required
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from ..compat import url_for
from ..constants import (
    ASTROMETRIC_CATALOGS,
    OPTICAL_FILTERS,
    PHOTOMETRIC_CATALOGS,
    STACK_MODES,
    TELESCOPES,
)
from ..extensions import db
from ..models import User
from ..services.auth import role_required
from ..services.jobs import owned_job
from ..services.prefect import (
    normalize_flow_run_for_ui,
    prefect_headers,
    prefect_url,
)

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/")
def index():
    return render_template("index.html")


@pages_bp.route("/about", methods=["GET"])
def about_page():
    return render_template("about.html")


@pages_bp.route("/profile")
@login_required
def user_page():
    return render_template("profile.html")


@pages_bp.route("/admin", methods=["GET", "POST"])
@role_required("admin")
def admin():
    users = User.query.order_by("username").all()

    if request.method == "POST":
        user_id = request.form.get("user_id")
        action = request.form.get("action")

        if user_id:
            user = User.query.get(user_id)

            if action == "remove":
                if user.role != "admin":
                    db.session.delete(user)
                    flash(f"User {user.username} removed successfully.")
                else:
                    flash(f"User {user.username} is admin and can not be removed")
            elif action == "ban":
                if user.id == current_user.id:
                    flash("You cannot ban yourself!", "danger")
                elif user.role == "admin":
                    flash(f"User {user.username} is admin and can not be banned")
                else:
                    user.role = "banned"
                    flash(f"User {user.username} banned successfully.")
            elif action == "change_role":
                new_role = request.form.get("new_role")
                if user.role == "admin":
                    flash(f"User {user.username} is admin and can not be downshifted")
                else:
                    user.role = new_role
                    flash(f"User {user.username} role changed to {new_role}.")
            elif action == "elevate_to_admin":
                if user.role == "admin":
                    flash(f"User {user.username} is already an admin.")
                else:
                    user.role = "admin"
                    flash(f"User {user.username} elevated to admin.")
            elif action == "unban":
                if user.id == current_user.id:
                    flash("You cannot unban yourself!", "danger")
                else:
                    user.role = "user"
                    flash(f"User {user.username} unbanned successfully.")

            db.session.commit()
            return redirect(url_for("admin"))

    return render_template("admin.html", users=users, current_user=current_user)


@pages_bp.route("/dag")
@role_required("admin")
def dag():
    response = requests.post(
        prefect_url("/deployments/filter"),
        headers=prefect_headers(),
        json={"limit": 200},
        timeout=10,
    )
    deployments = response.json() if response.status_code == 200 else []
    dags = [
        {
            "dag_id": d.get("id"),
            "dag_display_name": d.get("name"),
            "name": d.get("name"),
        }
        for d in deployments
    ]
    return render_template("dag.html", dags=dags)


@pages_bp.route("/dag/<dag_id>")
@role_required("admin")
def dag_details(dag_id):
    response = requests.post(
        prefect_url("/flow_runs/filter"),
        headers=prefect_headers(),
        json={
            "deployments": {"id": {"any_": [dag_id]}},
            "limit": 50,
            "sort": "START_TIME_DESC",
        },
        timeout=10,
    )
    flow_runs = response.json() if response.status_code == 200 else []
    dag_runs = [
        normalize_flow_run_for_ui(run, deployment_id=dag_id) for run in flow_runs
    ]

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template(
            "dag_runs_partial.html", dag_runs=dag_runs, dag_id=dag_id
        )

    return render_template("dag_details.html", dag_id=dag_id, dag_runs=dag_runs)


@pages_bp.route("/dag/<dag_id>/run/<run_id>")
@role_required("admin")
def dag_run_details(dag_id: str, run_id: str):
    response = requests.get(
        prefect_url(f"/flow_runs/{run_id}"),
        headers=prefect_headers(),
        timeout=10,
    )
    if response.status_code == 200:
        dag_run = normalize_flow_run_for_ui(response.json(), deployment_id=dag_id)
    else:
        dag_run = {
            "dag_id": dag_id,
            "dag_run_id": run_id,
            "execution_date": None,
            "state": "UNKNOWN",
            "start_date": None,
            "end_date": None,
        }

    return render_template("dag_run_details.html", dag_run=dag_run)


@pages_bp.route("/assets/js/js9/<path:path>", methods=["GET"])
def serve_js9_assets(path):
    # app.root_path is job-viewer/app; repo root is two levels up (same as legacy
    # Path(run_app.root_path).parent when run_app lived at job-viewer/).
    base_dir = (
        Path(current_app.root_path).parent.parent
        / "file-server"
        / "assets"
        / "js"
        / "js9"
    )
    return send_from_directory(base_dir, path)


@pages_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        lights = request.files.getlist("lights")
        darks = request.files.getlist("darks")
        flats = request.files.getlist("flats")
        if not lights:
            print("No light images to upload")
            return jsonify(
                {"status": "failed", "uploaded": 0, "reason": "no light images"}
            )

        job_id = uuid4().hex
        outdir = os.path.join(
            current_app.config["RESULT_FOLDER"], str(current_user.id), str(job_id)
        )
        light_dir = os.path.realpath(os.path.join(outdir, "lights"))
        dark_dir = os.path.realpath(os.path.join(outdir, "darks"))
        flat_dir = os.path.realpath(os.path.join(outdir, "flats"))

        def store_files(file_list: list[FileStorage], out_dir: str) -> list[str]:
            filenames = []
            for file in file_list:
                if file and file.filename.split(".")[-1] in [
                    "fit",
                    "fits",
                    "fts",
                    "zip",
                    "7z",
                    "gz",
                    "tar",
                    "rar",
                ]:
                    filename = secure_filename(file.filename)
                    os.makedirs(out_dir, exist_ok=True)
                    outpath = os.path.join(out_dir, filename)
                    file.save(outpath)
                    filenames.append(outpath)
            return filenames

        light_filenames = store_files(lights, light_dir)
        dark_filenames = store_files(darks, dark_dir)
        flat_filenames = store_files(flats, flat_dir)

        return jsonify(
            {
                "status": "successful",
                "working_dir": outdir,
                "subid": job_id,
                "light_filenames": light_filenames,
                "dark_filenames": dark_filenames,
                "flat_filenames": flat_filenames,
            }
        )

    return render_template(
        "upload.html",
        max_total_size=1024 * 1024 * 1024,
        telescopes=TELESCOPES,
        optical_filters=OPTICAL_FILTERS,
        stack_modes=STACK_MODES,
        astrometric_catalogs=ASTROMETRIC_CATALOGS,
        photometric_catalogs=PHOTOMETRIC_CATALOGS,
    )


@pages_bp.route("/submit/<subid>", methods=["GET"])
@login_required
def get_submit(subid: str):
    owned_job(subid)
    return render_template("submission.html", subid=subid)


@pages_bp.route("/view/<job_id>/<path:filename>", methods=["GET"])
@login_required
def view_image(job_id: str, filename: str):
    owned_job(job_id)
    return render_template("fits_view.html", job_id=job_id, filename=filename)
