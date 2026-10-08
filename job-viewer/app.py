import base64
from datetime import datetime, timezone
from functools import wraps
from io import BytesIO
from pathlib import Path
import struct
from uuid import uuid4
import zlib
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    render_template,
    request,
    redirect,
    url_for,
    send_file,
    send_from_directory,
    make_response,
    session,
)
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from flask_bootstrap import Bootstrap
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import os
import numpy as np
from astropy.io import fits
from flask_babel import Babel, _
from faker import Faker
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
import secrets
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage, FileMultiDict
from config import Config


# Telescopes (id, name in UI)
TELESCOPES = (("mondy_azt33ik", "Mondy/AZT-33IK"), ("abao_as32", "AbAO/AS-32"))

# Optical filters (id, name in UI)
OPTICAL_FILTERS = (
    ("clear", "Clear light"),
    ("Rc", "Rc"),
    ("Ic", "Ic"),
    ("Vj", "Vj"),
    ("Bj", "Bj"),
    ("Uj", "Uj"),
    ("u_sloan", "u'"),
    ("g_sloan", "g'"),
    ("r_sloan", "r'"),
    ("i_sloan", "i'"),
    ("z_sloan", "z'"),
)

# Stack modes (id, name in UI)
STACK_MODES = (
    ("none", "No stacking"),
    ("average", "Average"),
    ("median", "Median"),
    ("sum", "Sum"),
)

# Init application
app = Flask(__name__)
app.config.from_object(Config)

# Create folders
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["RESULT_FOLDER"], exist_ok=True)

fake = Faker()

app.secret_key = secrets.token_hex(16)  # Change this to a random secret key
Bootstrap(app)

babel = Babel(app)

# LANGUAGES = {"en": "English", "ru": "Русский"}


# def get_locale():
#     return request.accept_languages.best_match(LANGUAGES.keys())

# babel.init_app(app, locale_selector=get_locale)

# Set up Flask-SQLAlchemy
db = SQLAlchemy(app)


# Set up Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


def role_required(role):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login", next=request.url))
            if current_user.role != role:
                flash("You do not have permission to access this page.")
                return redirect(url_for("index"))
            return f(*args, **kwargs)

        return decorated_function

    return wrapper


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), nullable=False, default="user")  # Default role is 'user'
    signup_datetime = db.Column(db.DateTime, nullable=False, default=datetime.now(timezone.utc))
    last_login_datetime = db.Column(db.DateTime, nullable=False, default=datetime.now(timezone.utc))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_banned(self) -> bool:
        return self.role == "banned"

    def is_admin(self) -> bool:
        return self.role == "admin"

    jobs = db.relationship("Job", back_populates="user")


class Job(db.Model):
    __tablename__ = "job"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False)

    user = db.relationship("User", back_populates="jobs")
    user_id = db.Column(db.Integer, db.ForeignKey(User.id), nullable=False, index=True)


@app.route("/about", methods=["GET"])
def about_page():
    return render_template("about.html")


@app.route("/profile/update", methods=["POST"])
@login_required
def update_profile():
    data = request.get_json()
    new_username = data.get("username", "").strip()

    if not new_username:
        return jsonify({"status": "error", "message": "Username cannot be empty"}), 400

    # Check if username is already taken by someone else
    existing_user = User.query.filter_by(username=new_username).first()
    if existing_user and existing_user.id != current_user.id:
        return jsonify({"status": "error", "message": "Username already exists"}), 400

    current_user.username = new_username
    db.session.commit()
    return jsonify({"status": "success", "message": "Username updated successfully"})


@app.route("/profile/change-password", methods=["POST"])
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


with app.app_context():
    db.create_all()


def add_random_users(num_users):
    users = User.query.all()
    if len(users) < num_users:
        for _ in range(abs(len(users) - num_users)):
            name = fake.name()
            email = fake.unique.email()
            new_user = User(username=name)
            new_user.set_password(fake.name())
            db.session.add(new_user)
        db.session.commit()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if user and user.is_banned():
            flash("You was banned")

        if user and user.check_password(password):
            login_user(user)
            user.last_login_datetime = datetime.now(timezone.utc)
            db.session.commit()
            next_page = request.args.get("next")  # Get the next page from the query parameters
            return redirect(
                next_page or url_for("user_page")
            )  # Redirect to the next page or user page
        flash("Invalid username or password")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if User.query.filter_by(username=username).first():
            flash("Username already exists")
        else:
            new_user = User(username=username)
            new_user.set_password(password)  # Hash the password before storing
            db.session.add(new_user)
            db.session.commit()
            flash("Registration successful! You can now log in.")
            return redirect(url_for("login"))
    return render_template("signup.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/profile")
@login_required
def user_page():
    return render_template("profile.html")


@app.route("/admin", methods=["GET", "POST"])
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
            elif action == "unban":
                if user.id == current_user.id:
                    flash("You cannot unban yourself!", "danger")
                user.role = "user"
                flash(f"User {user.username} unbanned successfully.")

            db.session.commit()
            return redirect(url_for("admin"))

    return render_template("admin.html", users=users, current_user=current_user)


def standardize_status(state):
    state = (state or "").lower()
    mapping = {
        "success": "SUCCESS",
        "succeeded": "SUCCESS",
        "completed": "SUCCESS",
        "running": "RUNNING",
        "queued": "QUEUED",
        "scheduled": "QUEUED",
        "pending": "QUEUED",
        "deferred": "QUEUED",
        "awaitingretry": "QUEUED",
        "paused": "QUEUED",
        "cancelling": "RUNNING",
        "failed": "FAILED",
        "error": "FAILED",
        "crashed": "FAILED",
        "cancelled": "FAILED",
    }
    return mapping.get(state, "UNKNOWN")


def _extract_state_type(state) -> str:
    """Normalize Prefect state object or Airflow/plain string state."""
    if isinstance(state, dict):
        return state.get("type") or state.get("name") or ""
    return state or ""


def _prefect_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    api_key = app.config.get("PREFECT_API_KEY") or ""
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _prefect_url(path: str) -> str:
    base = app.config["PREFECT_API_URL"].rstrip("/")
    return f"{base}{path}"


def _resolve_prefect_deployment_id() -> str | None:
    deployment_id = (app.config.get("PREFECT_DEPLOYMENT_ID") or "").strip()
    if deployment_id:
        return deployment_id

    name = app.config.get("PREFECT_DEPLOYMENT_NAME") or ""
    response = requests.post(
        _prefect_url("/deployments/filter"),
        headers=_prefect_headers(),
        json={"deployments": {"name": {"any_": [name]}}, "limit": 1},
        timeout=10,
    )
    if response.status_code != 200:
        app.logger.error("Prefect deployment lookup failed: %s %s", response.status_code, response.text)
        return None
    deployments = response.json()
    if not deployments:
        app.logger.error("Prefect deployment not found: %s", name)
        return None
    return deployments[0].get("id")


def _get_prefect_flow_run_by_idempotency_key(key: str) -> dict | None:
    response = requests.post(
        _prefect_url("/flow_runs/filter"),
        headers=_prefect_headers(),
        json={
            "flow_runs": {"idempotency_key": {"any_": [key]}},
            "limit": 1,
            "sort": "START_TIME_DESC",
        },
        timeout=10,
    )
    if response.status_code != 200:
        app.logger.error(
            "Prefect flow-run lookup failed for %s: %s %s",
            key,
            response.status_code,
            response.text,
        )
        return None
    runs = response.json()
    return runs[0] if runs else None


def _normalize_flow_run_for_ui(flow_run: dict, deployment_id: str = "") -> dict:
    """Shape Prefect flow-run data like legacy Airflow dag-run fields for templates."""
    state_type = _extract_state_type(flow_run.get("state"))
    return {
        "dag_id": deployment_id or flow_run.get("deployment_id") or "",
        "dag_run_id": flow_run.get("id", ""),
        "execution_date": flow_run.get("expected_start_time")
        or flow_run.get("start_time")
        or flow_run.get("created"),
        "state": state_type,
        "start_date": flow_run.get("start_time"),
        "end_date": flow_run.get("end_time"),
        "name": flow_run.get("name"),
    }


# Airflow (legacy) — JWT wrapper for Airflow REST auth
# def jwt_required(f):
#     @wraps(f)
#     def decorated_function(*args, **kwargs):
#         token = session.get("jwt_token", "")
#         if not token:
#             print("No JWT token found in cookies, fetching from Airflow auth ..")
#             token_resp = requests.post(
#                 f"{app.config['AIRFLOW_URL']}/auth/token",
#                 json={
#                     "username": app.config["AIRFLOW_USERNAME"],
#                     "password": app.config["AIRFLOW_PASSWORD"],
#                 },
#             )
#
#             if token_resp.status_code == 201:
#                 token = token_resp.json().get("access_token", "")
#                 if token:
#                     session["jwt_token"] = token
#
#         return f(*args, **kwargs)
#
#     return decorated_function


@app.route("/dag")
@role_required("admin")
# @jwt_required  # Airflow (legacy)
def dag():
    # Prefect: list deployments
    response = requests.post(
        _prefect_url("/deployments/filter"),
        headers=_prefect_headers(),
        json={"limit": 200},
        timeout=10,
    )
    deployments = response.json() if response.status_code == 200 else []
    dags = [
        {"dag_id": d.get("id"), "dag_display_name": d.get("name"), "name": d.get("name")}
        for d in deployments
    ]

    # Airflow (legacy):
    # response = requests.get(
    #     f"{app.config['AIRFLOW_API_URL']}/dags",
    #     headers={"Authorization": f"Bearer {session.get('jwt_token')}"},
    # )
    # dags = response.json().get("dags", [])

    return render_template("dag.html", dags=dags)


@app.route("/dag/<dag_id>")
@role_required("admin")
# @jwt_required  # Airflow (legacy)
def dag_details(dag_id):
    # Prefect: list flow runs for a deployment
    response = requests.post(
        _prefect_url("/flow_runs/filter"),
        headers=_prefect_headers(),
        json={
            "deployments": {"id": {"any_": [dag_id]}},
            "limit": 50,
            "sort": "START_TIME_DESC",
        },
        timeout=10,
    )
    flow_runs = response.json() if response.status_code == 200 else []
    dag_runs = [_normalize_flow_run_for_ui(run, deployment_id=dag_id) for run in flow_runs]

    # Airflow (legacy):
    # response = requests.get(
    #     f"{app.config['AIRFLOW_API_URL']}/dags/{dag_id}/dagRuns",
    #     headers={"Authorization": f"Bearer {session.get('jwt_token')}"},
    # )
    # dag_runs = response.json().get("dag_runs", [])

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template("dag_runs_partial.html", dag_runs=dag_runs, dag_id=dag_id)

    return render_template("dag_details.html", dag_id=dag_id, dag_runs=dag_runs)


@app.route("/dag/<dag_id>/run/<run_id>")
@role_required("admin")
# @jwt_required  # Airflow (legacy)
def dag_run_details(dag_id: str, run_id: str):
    # Prefect: flow-run detail
    response = requests.get(
        _prefect_url(f"/flow_runs/{run_id}"),
        headers=_prefect_headers(),
        timeout=10,
    )
    if response.status_code == 200:
        dag_run = _normalize_flow_run_for_ui(response.json(), deployment_id=dag_id)
    else:
        dag_run = {
            "dag_id": dag_id,
            "dag_run_id": run_id,
            "execution_date": None,
            "state": "UNKNOWN",
            "start_date": None,
            "end_date": None,
        }

    # Airflow (legacy):
    # response = requests.get(
    #     f"{app.config['AIRFLOW_API_URL']}/dags/{dag_id}/dagRuns/{run_id}",
    #     headers={"Authorization": f"Bearer {session.get('jwt_token')}"},
    # )
    # dag_run = response.json()

    return render_template("dag_run_details.html", dag_run=dag_run)


@app.route("/api/dag/<dag_id>/run/<run_id>", methods=["GET"])
@login_required
def get_dag_run_details_ajax(dag_id: str, run_id: str):
    # Poll job status (run_id is local job_id / Prefect idempotency_key)
    job = Job.query.filter_by(job_id=run_id, user_id=current_user.id).one_or_none()
    if job is None:
        abort(404)

    active_statuses = {"RUNNING", "QUEUED", "running", "queued"}
    if job.status in active_statuses:
        # Prefect
        flow_run = _get_prefect_flow_run_by_idempotency_key(run_id)
        if flow_run:
            state_type = _extract_state_type(flow_run.get("state"))
            job.status = standardize_status(state_type)
            db.session.commit()
            dag_run_details = {
                "state": state_type.lower() if state_type else job.status.lower(),
                "dag_run_id": run_id,
                "flow_run_id": flow_run.get("id"),
            }
        else:
            dag_run_details = {"state": job.status.lower(), "dag_run_id": run_id}

        # Airflow (legacy):
        # response = requests.get(
        #     f"{app.config['AIRFLOW_API_URL']}/dags/{dag_id}/dagRuns/{run_id}",
        #     headers={"Authorization": f"Bearer {session.get('jwt_token')}"},
        # )
        # if response.status_code == 200:
        #     dag_run_details = response.json()
        #     job.status = standardize_status(dag_run_details.get("state", job.status))
        #     db.session.commit()
        # else:
        #     dag_run_details = {"state": job.status, "dag_run_id": run_id}
    else:
        dag_run_details = {"state": job.status.lower(), "dag_run_id": run_id}

    return jsonify(dag_run_details)


def _owned_job(job_id: str) -> Job:
    job = Job.query.filter_by(job_id=job_id, user_id=current_user.id).one_or_none()
    print(job)
    if job is None:
        abort(404)
    return job


def _job_result_directory(job: Job) -> Path:
    user_directory = (Path(app.config["RESULT_FOLDER"]) / str(job.user_id)).resolve()
    job_directory = (user_directory / job.job_id).resolve()
    if not job_directory.is_relative_to(user_directory):
        abort(404)
    return job_directory


def _resolve_job_artifact(job: Job, filename: str) -> Path:
    job_directory = _job_result_directory(job)
    artifact = job_directory / filename
    if artifact.is_symlink():
        abort(404)
    artifact = artifact.resolve()
    if not artifact.is_relative_to(job_directory) or not artifact.is_file():
        abort(404)
    return artifact


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    chunk = chunk_type + data
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk))


def _fits_preview_png(filename: Path) -> bytes:
    try:
        raw_data = fits.getdata(filename, 0, memmap=True)
    except ValueError:
        raw_data = fits.getdata(filename, 0, memmap=False)
    if raw_data is None:
        raise ValueError("FITS image has no primary data")
    data = np.asarray(raw_data)
    while data.ndim > 2:
        data = data[0]
    if data.ndim != 2:
        raise ValueError("FITS image must contain a two-dimensional image")

    stride = max(1, int(np.ceil(max(data.shape) / 1200)))
    pixels = np.asarray(data[::stride, ::stride], dtype=np.float32)

    finite = np.isfinite(pixels)
    if not finite.any():
        raise ValueError("FITS image contains no finite pixels")

    low, high = np.percentile(pixels[finite], (1, 99))
    if high <= low:
        scaled = np.where(finite, 127, 0).astype(np.uint8)
    else:
        scaled = np.clip(
            (np.nan_to_num(pixels, nan=low, posinf=high, neginf=low) - low)
            * (255.0 / (high - low)),
            0,
            255,
        ).astype(np.uint8)

    height, width = scaled.shape
    scaled = np.flipud(scaled)
    rows = b"".join(b"\x00" + row.tobytes() for row in scaled)
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(rows))
        + _png_chunk(b"IEND", b"")
    )


@app.route("/assets/js/js9/<path:path>", methods=["GET"])
def serve_js9_assets(path):
    # The assets are located in file-server/assets/js/js9
    # We need to map this directory to the /assets/js/js9 route
    # Assuming the app is running from the 'job-viewer' directory
    # We go up one level then into file-server/assets/js/js9
    base_dir = Path(app.root_path).parent / "file-server" / "assets" / "js" / "js9"
    return send_from_directory(base_dir, path)


@app.route("/api/jobs/<job_id>/raw/<path:filename>", methods=["GET"])
@login_required
def get_job_raw(job_id: str, filename: str):
    job = _owned_job(job_id)
    artifact = _resolve_job_artifact(job, filename)
    return send_from_directory(
        artifact.parent, artifact.name, as_attachment=False
    )


@app.route("/api/jobs/<job_id>/regions/<path:filename>", methods=["GET"])
@login_required
def get_job_regions(job_id: str, filename: str):
    job = _owned_job(job_id)
    # Ensure the filename is a .reg file and stays within the job directory
    if not filename.endswith(".reg"):
        abort(400)

    artifact = _resolve_job_artifact(job, filename)

    try:
        with open(artifact, "r") as f:
            content = f.read()
        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/jobs/<job_id>/results", methods=["GET"])
@login_required
def get_job_results(job_id: str):
    job = _owned_job(job_id)
    job_directory = _job_result_directory(job)
    if not job_directory.is_dir():
        return jsonify({"files": [], "truncated": False})

    preview_extensions = {
        ".bmp",
        ".fit",
        ".fits",
        ".fts",
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".webp",
    }
    artifacts = []
    for artifact in job_directory.rglob("*"):
        if artifact.is_symlink() or not artifact.is_file():
            continue
        resolved = artifact.resolve()
        if not resolved.is_relative_to(job_directory):
            continue
        relative_name = artifact.relative_to(job_directory).as_posix()

        # If it's a .reg file, we list it for download,
        # but we don't treat it as a primary preview image.
        if relative_name.endswith(".reg"):
            item = {
                "name": relative_name,
                "size": artifact.stat().st_size,
                "download_url": url_for(
                    "download_job_result", job_id=job.job_id, filename=relative_name
                ),
            }
            artifacts.append(item)
            continue

        item = {
            "name": relative_name,
            "size": artifact.stat().st_size,
            "download_url": url_for(
                "download_job_result", job_id=job.job_id, filename=relative_name
            ),
        }
        if artifact.suffix.lower() in preview_extensions:
            item["preview_url"] = url_for(
                "preview_job_result", job_id=job.job_id, filename=relative_name
            )

            # Check for associated .reg file
            reg_path = artifact.with_suffix(".reg")
            if reg_path.exists():
                item["reg_url"] = url_for(
                    "get_job_regions", job_id=job.job_id, filename=reg_path.name
                )

            # Get original dimensions for coordinate scaling
            try:
                if artifact.suffix.lower() in {".fit", ".fits", ".fts"}:
                    with fits.open(artifact) as hdul:
                        header = hdul[0].header
                        item["original_dimensions"] = {
                            "width": header.get("NAXIS1", 0),
                            "height": header.get("NAXIS2", 0),
                        }
                else:
                    # For standard images, we can use PIL or just skip if not available
                    # For now, we'll use a simple approach or add PIL
                    item["original_dimensions"] = None
            except Exception:
                item["original_dimensions"] = None

        artifacts.append(item)

    artifacts.sort(key=lambda item: item["name"].lower())
    return jsonify({"files": artifacts[:200], "truncated": len(artifacts) > 200})


@app.route("/api/jobs/<job_id>/results/<path:filename>", methods=["GET"])
@login_required
def download_job_result(job_id: str, filename: str):
    job = _owned_job(job_id)
    artifact = _resolve_job_artifact(job, filename)
    return send_from_directory(
        artifact.parent, artifact.name, as_attachment=True, download_name=artifact.name
    )


@app.route("/api/jobs/<job_id>/preview/<path:filename>", methods=["GET"])
@login_required
def preview_job_result(job_id: str, filename: str):
    job = _owned_job(job_id)
    artifact = _resolve_job_artifact(job, filename)
    if artifact.suffix.lower() in {".fit", ".fits", ".fts"}:
        try:
            preview = _fits_preview_png(artifact)
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


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        lights = request.files.getlist("lights")
        darks = request.files.getlist("darks")
        flats = request.files.getlist("flats")
        if not lights:
            print("No light images to upload")
            return jsonify({"status": "failed", "uploaded": 0, "reason": "no light images"})

        job_id = uuid4().hex
        outdir = os.path.join(app.config["RESULT_FOLDER"], str(current_user.id), str(job_id))
        light_dir = os.path.realpath(os.path.join(outdir, "lights"))
        dark_dir = os.path.realpath(os.path.join(outdir, "darks"))
        flat_dir = os.path.realpath(os.path.join(outdir, "flats"))

        light_filenames = []

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
    )


@app.route("/submit", methods=["POST"])
@login_required
# @jwt_required  # Airflow (legacy)
def post_submit():
    data = request.json

    # Extract additional configuration from the request
    apex_conf = data.get("apex_conf", "default")
    astrometric_catalog = data.get("astrometric_catalog", "gaia")
    transient_circle = data.get("transient_circle", {})

    ra_field = data.get("ra_field")
    dec_field = data.get("dec_field")

    # Handle transient_circle if it's passed as an object from the new frontend
    if isinstance(transient_circle, dict):
        # Format: "RA, DEC, RADIUS" or similar for the DAG to parse
        circle_str = f"{transient_circle.get('ra', '0')},{transient_circle.get('dec', '0')},{transient_circle.get('radius', '10')}"
    else:
        circle_str = transient_circle

    # Airflow (legacy) request body — kept for rollback
    body = {
        "conf": {
            "working_dir": data["working_dir"],
            "light_filenames": data["light_filenames"],
            "dark_filenames": data["dark_filenames"],
            "flat_filenames": data["flat_filenames"],
            "apex_conf": apex_conf,
            "astrometric_catalog": astrometric_catalog,
            "transient_circle": circle_str,
            "telescope": data.get("telescope"),
            "stack_mode": data.get("stack_mode"),
            "group_frames": data.get("group_frames"),
            "group_frames_value": data.get("group_frames_value"),
            "filter": data.get("filter"),
            "photometric_catalog": data.get("photometric_catalog"),
            "ra_field": ra_field,
            "dec_field": dec_field,
        },
        "dag_run_id": data["subid"],
        "logical_date": datetime.now().astimezone().isoformat(),
    }

    deployment_id = _resolve_prefect_deployment_id()
    if not deployment_id:
        return jsonify(
            {
                "status": "failed",
                "subid": data["subid"],
                "reason": "Prefect deployment not found",
            }
        ), 500

    response = requests.post(
        _prefect_url(f"/deployments/{deployment_id}/create_flow_run"),
        headers=_prefect_headers(),
        json={
            "name": data["subid"],
            "idempotency_key": data["subid"],
            "parameters": {
                "working_dir": data["working_dir"],
                "light_filenames": data.get("light_filenames") or [],
                "dark_filenames": data.get("dark_filenames") or [],
                "flat_filenames": data.get("flat_filenames") or [],
                "telescope": data.get("telescope"),
                "options": {
                    "apex_conf": apex_conf,
                    "astrometric_catalog": astrometric_catalog,
                    "transient_circle": circle_str,
                    "stack_mode": data.get("stack_mode"),
                    "group_frames": data.get("group_frames"),
                    "group_frames_value": data.get("group_frames_value"),
                    "filter": data.get("filter"),
                    "photometric_catalog": data.get("photometric_catalog"),
                    "ra_field": ra_field,
                    "dec_field": dec_field,
                },
            },
        },
        timeout=30,
    )

    # Hardcoded deployment UUID (previous mid-migration attempt):
    # response = requests.post(
    #     "http://127.0.0.1:4200/api/deployments/77ca8c5e-5a99-4370-a79d-1c65018b1cde/create_flow_run",
    #     json={
    #         "idempotency_key": data["subid"],
    #         "parameters": {
    #             "working_dir": data["working_dir"],
    #             "light_filenames": data["light_filenames"],
    #             "dark_filenames": data["dark_filenames"],
    #         },
    #     },
    # )

    try:
        json_resp = response.json()
    except ValueError:
        json_resp = {"raw": response.text}
    print(json_resp)

    # Airflow (legacy):
    # response = requests.post(
    #     f"{app.config['AIRFLOW_API_URL']}/dags/process_image/dagRuns",
    #     json=body,
    #     headers={"Authorization": f"Bearer {session.get('jwt_token')}"},
    # )
    # json_resp = response.json()
    # print(json_resp)

    if response.status_code in (200, 201):
        state_type = _extract_state_type(json_resp.get("state"))
        job = Job(
            user_id=current_user.id,
            job_id=data["subid"],
            status=standardize_status(state_type or "PENDING"),
        )
        db.session.add(job)
        db.session.commit()
        return jsonify({"status": "successful", "subid": data["subid"]})

    return jsonify({"status": "failed", "subid": data["subid"], "reason": json_resp}), 500


@app.route("/api/jobs/update/<job_id>", methods=["POST"])
def update_job(job_id: str):
    """
    !TODO: Update several fields: start_date, end_date, status
    """
    data = request.get_json()
    job = Job.query.filter_by(job_id=job_id).one_or_none()
    if not job:
        return jsonify({"status": "fail", "reason": f"job with job_id={job_id} not found"})
    if data.get("status", ''):
        new_status = standardize_status(data["status"])
        db.session.query(Job).filter_by(job_id=job_id).update({"status": new_status})
        db.session.commit()
    else:
        return jsonify({"status": "fail", "reason": f"status for job_id={job_id} not fetched"})
    return jsonify({"status": "success"})


@app.route("/submit/<subid>", methods=["GET"])
@login_required
def get_submit(subid: str):
    _owned_job(subid)
    return render_template("submission.html", subid=subid)


@app.route("/view/<job_id>/<path:filename>", methods=["GET"])
@login_required
def view_image(job_id: str, filename: str):
    _owned_job(job_id)
    return render_template("js9_view.html", job_id=job_id, filename=filename)


@app.route("/user/<user_id>/submissions", methods=["GET"])
@login_required
def get_user_submitions_ajax(user_id: int):
    user = User.query.filter_by(id=user_id).one_or_none()
    if not user:
        return jsonify({"status": "failed"})

    query_str = request.args.get('q', '').strip()

    # Proactive sync: Update any jobs that are still marked as RUNNING or QUEUED
    # We'll sync only the jobs that are actually returned to the user
    all_jobs = user.jobs

    # Filter by query string if provided
    if query_str:
        filtered_jobs = [job for job in all_jobs if query_str.lower() in job.job_id.lower()]
    else:
        filtered_jobs = all_jobs

    # Sync statuses for the jobs we are about to return
    running_jobs = [job for job in filtered_jobs if job.status in ["RUNNING", "QUEUED", "running", "queued"]]
    for job in running_jobs:
        try:
            # Prefect
            flow_run = _get_prefect_flow_run_by_idempotency_key(job.job_id)
            if flow_run:
                job.status = standardize_status(_extract_state_type(flow_run.get("state")))
                db.session.commit()

            # Airflow (legacy):
            # response = requests.get(
            #     f"{app.config['AIRFLOW_API_URL']}/dags/process_image/dagRuns/{job.job_id}",
            #     headers={"Authorization": f"Bearer {session.get('jwt_token')}"},
            #     timeout=2
            # )
            # if response.status_code == 200:
            #     new_state = response.json().get("state")
            #     job.status = standardize_status(new_state)
            #     db.session.commit()
        except Exception as e:
            app.logger.error(f"Failed to proactively sync job {job.job_id}: {e}")

    jobs = [{"subid": job.job_id, "status": job.status} for job in filtered_jobs]

    return jsonify({"status": "successful", "submissions": jobs})


@app.route("/api/internal/job-complete", methods=["POST"])
def job_complete():
    data = request.json
    job_id = data.get("job_id")
    results = data.get("results")

    # Logic to save 'results' to your DB for 'job_id'
    # update_job_in_db(job_id, results, status='SUCCESS')
    db.session.query(Job).filter_by(user_id=current_user.id).update(
        {Job.job_id: job_id, Job.status: "success"}
    )
    db.session.commit()

    return jsonify({"status": "received"}), 200


# hdr = fits.getheader(outpath)

# body = {
#     "conf": {
#         "filename": Path(filename).name,
#         "telescope": hdr.get("telescope", ""),
#         "observatory": hdr.get("observatory", ""),
#         "camera": hdr.get("camera", ""),
#         "filter": hdr.get("filter", ""),
#     },
#     "dag_run_id": job_id,
# }

# # Запуск DAG для обработки изображения
# response = requests.post(
#     f"{AIRFLOW_API_URL}/dags/process_image/dagRuns", json=body, headers=AUTH_HEADERS
# )

# if response.status_code == 200:
#     return redirect(
#         url_for("dag_run_details", dag_id="process_image", run_id=body["dag_run_id"])
#     )
# else:
#     return "Error starting DAG", 500


if __name__ == "__main__":
    with app.app_context():
        # Specify the number of random users to add
        num_users_to_add = 100
        add_random_users(num_users_to_add)
        print(f"Added {num_users_to_add} random users to the database.")

        existing_admin = User.query.filter_by(username="admin").first()
        if existing_admin:
            print("Admin user already exists.")
        else:
            # Create a new admin user
            new_admin = User(username="admin", role="admin")
            new_admin.set_password("admin")
            db.session.add(new_admin)
            db.session.commit()
            print("Admin user created successfully.")

    app.run(debug=True)
