import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    UPLOAD_FOLDER = os.environ.get("JOBVIEWER_UPLOAD_FOLDER", "../uploads")
    RESULT_FOLDER = os.environ.get(
        "JOBVIEWER_RESULT_FOLDER", "/home/halo/airflow/processed_images"
    )
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "JOBVIEWER_DATABASE_URI", "sqlite:///users.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Persistent session signing key (set SECRET_KEY in production).
    SECRET_KEY = os.environ.get("SECRET_KEY") or os.environ.get(
        "JOBVIEWER_SECRET_KEY", ""
    )

    # Prefect (active)
    PREFECT_API_URL = os.environ.get("PREFECT_API_URL", "http://127.0.0.1:4200/api")
    PREFECT_DEPLOYMENT_NAME = os.environ.get(
        "PREFECT_DEPLOYMENT_NAME", "Image-Processing"
    )
    PREFECT_DEPLOYMENT_ID = os.environ.get("PREFECT_DEPLOYMENT_ID", "")
    PREFECT_API_KEY = os.environ.get("PREFECT_API_KEY", "")

    # Shared secret for worker callbacks (POST /api/jobs/update, /api/internal/job-complete).
    JOBVIEWER_CALLBACK_TOKEN = os.environ.get("JOBVIEWER_CALLBACK_TOKEN")

    # Only create default admin when explicitly enabled (dev).
    BOOTSTRAP_ADMIN = os.environ.get("JOBVIEWER_BOOTSTRAP_ADMIN", "").lower() in {
        "1",
        "true",
        "yes",
    }
    BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("JOBVIEWER_BOOTSTRAP_ADMIN_PASSWORD", "")

    # Airflow (legacy — kept for rollback; set via env if re-enabled)
    # AIRFLOW_USERNAME = os.environ.get("AIRFLOW_USERNAME", "")
    # AIRFLOW_PASSWORD = os.environ.get("AIRFLOW_PASSWORD", "")
    # AIRFLOW_URL = os.environ.get("AIRFLOW_URL", "http://localhost:8881")
    # AIRFLOW_API_URL = f"{AIRFLOW_URL}/api/v2"
