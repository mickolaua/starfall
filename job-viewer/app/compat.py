"""Map legacy bare endpoint names (used in shared templates) to blueprint endpoints."""

from flask import url_for as flask_url_for

# Bare names from run_app.py / templates → blueprint.endpoint
ENDPOINT_ALIASES = {
    "index": "pages.index",
    "about_page": "pages.about_page",
    "user_page": "pages.user_page",
    "admin": "pages.admin",
    "upload": "pages.upload",
    "get_submit": "pages.get_submit",
    "view_image": "pages.view_image",
    "dag": "pages.dag",
    "dag_details": "pages.dag_details",
    "dag_run_details": "pages.dag_run_details",
    "serve_js9_assets": "pages.serve_js9_assets",
    "login": "auth.login",
    "signup": "auth.signup",
    "logout": "auth.logout",
    "get_dag_run_details_ajax": "api_status.get_dag_run_details_ajax",
    "get_user_submitions_ajax": "api_status.get_user_submitions_ajax",
    "post_submit": "api_status.post_submit",
    "update_profile": "api_status.update_profile",
    "change_password": "api_status.change_password",
    "get_job_raw": "api_jobs.get_job_raw",
    "get_job_regions": "api_jobs.get_job_regions",
    "get_job_results": "api_jobs.get_job_results",
    "get_job_text_preview": "api_jobs.get_job_text_preview",
    "download_job_result": "api_jobs.download_job_result",
    "preview_job_result": "api_jobs.preview_job_result",
    "get_job_fits_header": "api_jobs.get_job_fits_header",
    "parse_job_overlay": "api_jobs.parse_job_overlay",
    "get_job_overlay": "api_jobs.get_job_overlay",
    "update_job": "callbacks.update_job",
    "job_complete": "callbacks.job_complete",
}


def url_for(endpoint: str, **values):
    """url_for that accepts legacy bare endpoint names used by shared templates."""
    return flask_url_for(ENDPOINT_ALIASES.get(endpoint, endpoint), **values)


def install_template_url_for(app) -> None:
    """Override Jinja url_for so shared templates keep working with blueprints."""
    app.jinja_env.globals["url_for"] = url_for
