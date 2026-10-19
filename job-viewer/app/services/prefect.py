import requests
from flask import current_app


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


def extract_state_type(state) -> str:
    """Normalize Prefect state object or Airflow/plain string state."""
    if isinstance(state, dict):
        return state.get("type") or state.get("name") or ""
    return state or ""


def prefect_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    api_key = current_app.config.get("PREFECT_API_KEY") or ""
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def prefect_url(path: str) -> str:
    base = current_app.config["PREFECT_API_URL"].rstrip("/")
    return f"{base}{path}"


def resolve_prefect_deployment_id() -> str | None:
    deployment_id = (current_app.config.get("PREFECT_DEPLOYMENT_ID") or "").strip()
    if deployment_id:
        return deployment_id

    name = current_app.config.get("PREFECT_DEPLOYMENT_NAME") or ""
    response = requests.post(
        prefect_url("/deployments/filter"),
        headers=prefect_headers(),
        json={"deployments": {"name": {"any_": [name]}}, "limit": 1},
        timeout=10,
    )
    if response.status_code != 200:
        current_app.logger.error(
            "Prefect deployment lookup failed: %s %s",
            response.status_code,
            response.text,
        )
        return None
    deployments = response.json()
    if not deployments:
        current_app.logger.error("Prefect deployment not found: %s", name)
        return None
    return deployments[0].get("id")


def get_prefect_flow_run_by_idempotency_key(key: str) -> dict | None:
    response = requests.post(
        prefect_url("/flow_runs/filter"),
        headers=prefect_headers(),
        json={
            "flow_runs": {"idempotency_key": {"any_": [key]}},
            "limit": 1,
            "sort": "START_TIME_DESC",
        },
        timeout=10,
    )
    if response.status_code != 200:
        current_app.logger.error(
            "Prefect flow-run lookup failed for %s: %s %s",
            key,
            response.status_code,
            response.text,
        )
        return None
    runs = response.json()
    return runs[0] if runs else None


def get_prefect_flow_run_by_id(flow_run_id: str) -> dict | None:
    if not flow_run_id:
        return None
    response = requests.get(
        prefect_url(f"/flow_runs/{flow_run_id}"),
        headers=prefect_headers(),
        timeout=10,
    )
    if response.status_code != 200:
        current_app.logger.error(
            "Prefect flow-run get failed for %s: %s %s",
            flow_run_id,
            response.status_code,
            response.text,
        )
        return None
    return response.json()


def get_latest_prefect_flow_run_for_job(job_id: str) -> dict | None:
    """Latest flow run for a job (original idempotency key or retry-* names)."""
    response = requests.post(
        prefect_url("/flow_runs/filter"),
        headers=prefect_headers(),
        json={
            "flow_runs": {
                "name": {"like_": f"{job_id}%"},
            },
            "limit": 5,
            "sort": "START_TIME_DESC",
        },
        timeout=10,
    )
    if response.status_code != 200:
        # Fallback: idempotency key exact / prefix via any_ original key
        return get_prefect_flow_run_by_idempotency_key(job_id)
    runs = response.json() or []
    if runs:
        return runs[0]
    return get_prefect_flow_run_by_idempotency_key(job_id)


def cancel_prefect_flow_run(flow_run_id: str) -> bool:
    response = requests.post(
        prefect_url(f"/flow_runs/{flow_run_id}/set_state"),
        headers=prefect_headers(),
        json={"state": {"type": "CANCELLED", "message": "Cancelled by user"}},
        timeout=15,
    )
    if response.status_code not in (200, 201):
        current_app.logger.error(
            "Prefect cancel failed for %s: %s %s",
            flow_run_id,
            response.status_code,
            response.text,
        )
        return False
    return True


def normalize_flow_run_for_ui(flow_run: dict, deployment_id: str = "") -> dict:
    """Shape Prefect flow-run data like legacy Airflow dag-run fields for templates."""
    state_type = extract_state_type(flow_run.get("state"))
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
