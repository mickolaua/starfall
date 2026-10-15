import json
from datetime import datetime, timezone

from ..extensions import db

_TERMINAL_STATUSES = frozenset({"SUCCESS", "FAILED"})
_ACTIVE_STATUSES = frozenset({"RUNNING", "QUEUED"})


class Job(db.Model):
    __tablename__ = "job"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    stack_mode = db.Column(db.String(50), nullable=True)
    job_parameters = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", back_populates="jobs")
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, index=True
    )

    def set_job_parameters(self, params: dict) -> None:
        """Serialize task input parameters (must not include lifecycle status)."""
        if params is None:
            self.job_parameters = None
            return
        clean = {k: v for k, v in params.items() if k != "status"}
        self.job_parameters = json.dumps(clean, ensure_ascii=False)

    def get_job_parameters(self) -> dict | None:
        if not self.job_parameters:
            return None
        try:
            data = json.loads(self.job_parameters)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        # Lifecycle status is never taken from parameters JSON.
        data.pop("status", None)
        return data


def apply_job_status(job: Job, new_status: str, *, now: datetime | None = None) -> None:
    """
    Update Job.status and started_at / finished_at.
    Status must come from this path (or create), never from job_parameters JSON.
    """
    from ..services.prefect import standardize_status

    status = standardize_status(new_status)
    job.status = status
    ts = now or datetime.now(timezone.utc)

    if status in _ACTIVE_STATUSES and job.started_at is None:
        job.started_at = ts
    if status in _TERMINAL_STATUSES and job.finished_at is None:
        job.finished_at = ts
