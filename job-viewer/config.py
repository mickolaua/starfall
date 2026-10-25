import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Config:
    UPLOAD_FOLDER = os.environ.get("JOBVIEWER_UPLOAD_FOLDER", "../uploads")
    RESULT_FOLDER = os.environ.get(
        "JOBVIEWER_RESULT_FOLDER", "/opt/job-viewer/uploads"
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
    TALISMAN_ENABLE_STRICT_HTTPS = os.environ.get("JOBVIEWER_TALISMAN_ENABLE_STRICT_HTTPS", False)
    LIMITER_STORAGE_URI = os.environ.get("JOBVIEWER_LIMITER_STORAGE_URI", "memory://")
    LIMITER_DEFAULT_LIMITS = ["1000 per hour", "10 per second", "10000 per day"]

    CSP = {
        'default-src': '\'self\'',
        'script-src': [
            '\'self\'',
            'https://jsdelivr.net',      # Allows specific external CDNs
            'https://code.jquery.com',
            'https://cdn.jsdelivr.net',
            'https://unpkg.com/',
             "'unsafe-inline'" # Swagger
        ],
        'style-src': [
            '\'self\'',
            'https://cdn.jsdelivr.net',
            'https://googleapis.com',  # Allows Google Fonts CSS
            '\'unsafe-inline\'', # WARNING: Allows inline <style> tags
            'https://unpkg.com/',
             "'unsafe-inline'" # Swagger       
        ],
        'font-src': [
            '\'self\'',
            'https://cdn.jsdelivr.net',
            'https://gstatic.com'      # Allows actual font files
        ],
        'img-src': [
            '\'self\'',
            'https://unsplash.com',   # Allows loading external imagery
            "https://icons.getbootstrap.com/",
            'data:'                          # Allows base64 encoded images
        ]
    }

    LOGS_FOLDER = os.environ.get("JOBVIEWER_LOGS_FOLDER", str(Path(__file__).resolve().parent / "logs"))
    LOGS_CONFIG_FILENAME = os.environ.get("JOBVIEWER_LOGS_CONFIG_FILENAME", "loggers.ini")

    # Airflow (legacy — kept for rollback; set via env if re-enabled)
    # AIRFLOW_USERNAME = os.environ.get("AIRFLOW_USERNAME", "")
    # AIRFLOW_PASSWORD = os.environ.get("AIRFLOW_PASSWORD", "")
    # AIRFLOW_URL = os.environ.get("AIRFLOW_URL", "http://localhost:8881")
    # AIRFLOW_API_URL = f"{AIRFLOW_URL}/api/v2"
