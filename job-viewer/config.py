import json
import os
from copy import deepcopy
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return list(default)
    return [part.strip() for part in raw.split(",") if part.strip()]


_DEFAULT_CSP = {
    "default-src": "'self'",
    "font-src": [
        "'self'",
        "https://cdn.jsdelivr.net",
        "https://fonts.googleapis.com",
        "https://fonts.gstatic.com",
    ],
    "script-src": [
        "'self'",
        "'unsafe-hashes'",
        "https://cdn.jsdelivr.net",
        "https://unpkg.com",
    ],
    "style-src": [
        "'self'",
        "'unsafe-hashes'",
        "https://cdn.jsdelivr.net",
        "https://fonts.googleapis.com",
        "https://unpkg.com",
        # Common style= attributes (legacy markup / unsafe-hashes fallback)
        "'sha256-0EZqoz+oBhx7gF4nvY2bSqoGyy4zLjNF+SDQXGp/ZrY='",  # display:none;
        "'sha256-biLFinpqYMtWHmXfkA1BPeCY0/fNt46SAZ+BBk5YUog='",  # display: none;
        "'sha256-aqNNdDLnnrDOnTNdkJpYlAxKVJtLt9CtFLklmInuUAE='",  # display:none
        "'sha256-5TmCSWsRHHKtNC4AgS23KS5Z9SBqma0xikI6H6iJ1/Y='",  # display:block;
        "'sha256-uEZIW979MhGuVYezoiKwoQbYu4l7po9cGyRisJdYKwQ='",
        "'sha256-psj1BN9ilCcIY3WMPF503xQJheWX2ZbFMUY6ABugIk4='",
        "'sha256-Tc7UYCuxD441v2GobH38053QqYDdIRKyuzjF0NMB/Ss='",
    ],
    "img-src": ["'self'", "data:"],
}


def _load_csp() -> dict:
    policy = deepcopy(_DEFAULT_CSP)
    raw = os.environ.get("JOBVIEWER_CSP_JSON", "").strip()
    if not raw:
        return policy
    try:
        override = json.loads(raw)
    except json.JSONDecodeError:
        return policy
    if not isinstance(override, dict):
        return policy
    # Replace entire policy when JSON is provided (deploy-time full override).
    return override


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

    # --- Talisman / CSP (read by create_app) ---
    TALISMAN_FORCE_HTTPS = _env_bool(
        "JOBVIEWER_TALISMAN_ENABLE_STRICT_HTTPS", False
    )
    # Back-compat alias used by older code paths.
    TALISMAN_ENABLE_STRICT_HTTPS = TALISMAN_FORCE_HTTPS
    TALISMAN_CONTENT_SECURITY_POLICY = _load_csp()
    TALISMAN_CONTENT_SECURITY_POLICY_NONCE_IN = _env_csv(
        "JOBVIEWER_TALISMAN_CSP_NONCE_IN",
        ["script-src", "style-src", "font-src"],
    )
    TALISMAN_CSP_REPORT_ONLY = _env_bool("JOBVIEWER_TALISMAN_CSP_REPORT_ONLY", False)
    TALISMAN_CSP_REPORT_URI = os.environ.get(
        "JOBVIEWER_TALISMAN_CSP_REPORT_URI", "/api/v1/csp-report"
    )
    TALISMAN_FRAME_OPTIONS = os.environ.get("JOBVIEWER_TALISMAN_FRAME_OPTIONS", "SAMEORIGIN")
    # Empty string disables HSTS; set e.g. "max-age=31536000; includeSubDomains"
    TALISMAN_STRICT_TRANSPORT_SECURITY = os.environ.get(
        "JOBVIEWER_TALISMAN_STRICT_TRANSPORT_SECURITY", ""
    )

    # --- Flask-Limiter (per-route; no global default_limits) ---
    LIMITER_STORAGE_URI = os.environ.get("JOBVIEWER_LIMITER_STORAGE_URI", "memory://")
    LIMITER_AUTH = os.environ.get("JOBVIEWER_LIMITER_AUTH", "10 per minute")
    LIMITER_API_READ = os.environ.get("JOBVIEWER_LIMITER_API_READ", "120 per minute")
    LIMITER_API_WRITE = os.environ.get("JOBVIEWER_LIMITER_API_WRITE", "30 per minute")
    LIMITER_CALLBACK = os.environ.get("JOBVIEWER_LIMITER_CALLBACK", "120 per minute")
    LIMITER_CSP_REPORT = os.environ.get("JOBVIEWER_LIMITER_CSP_REPORT", "60 per minute")

    LOGS_FOLDER = os.environ.get(
        "JOBVIEWER_LOGS_FOLDER", str(Path(__file__).resolve().parent / "logs")
    )
    LOGS_CONFIG_FILENAME = os.environ.get(
        "JOBVIEWER_LOGS_CONFIG_FILENAME", "loggers.ini"
    )

    # Airflow (legacy — kept for rollback; set via env if re-enabled)
    # AIRFLOW_USERNAME = os.environ.get("AIRFLOW_USERNAME", "")
    # AIRFLOW_PASSWORD = os.environ.get("AIRFLOW_PASSWORD", "")
    # AIRFLOW_URL = os.environ.get("AIRFLOW_URL", "http://localhost:8881")
    # AIRFLOW_API_URL = f"{AIRFLOW_URL}/api/v2"
