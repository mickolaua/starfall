from ..extensions import db


class Job(db.Model):
    __tablename__ = "job"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    stack_mode = db.Column(db.String(50), nullable=True)

    user = db.relationship("User", back_populates="jobs")
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, index=True
    )


def ensure_job_schema() -> None:
    """Add columns that create_all will not add to an existing SQLite table."""
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    if "job" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("job")}
    if "stack_mode" not in columns:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE job ADD COLUMN stack_mode VARCHAR(50)"))
