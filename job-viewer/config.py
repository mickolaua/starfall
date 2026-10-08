class Config:
    UPLOAD_FOLDER = "../uploads"
    RESULT_FOLDER = "/home/halo/airflow/processed_images"
    SQLALCHEMY_DATABASE_URI = "sqlite:///users.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Prefect (active)
    PREFECT_API_URL = "http://127.0.0.1:4200/api"
    PREFECT_DEPLOYMENT_NAME = "Image-Processing"
    # Optional: set explicitly to skip name lookup. Leave empty to resolve by name.
    PREFECT_DEPLOYMENT_ID = ""
    PREFECT_API_KEY = ""  # set if Prefect auth is enabled

    # Airflow (legacy — kept for rollback)
    # AIRFLOW_USERNAME = "admin"
    # AIRFLOW_PASSWORD = "cKuXMNzR5xdu8Tm5"
    # AIRFLOW_URL = "http://localhost:8881"
    # AIRFLOW_API_URL = f"{AIRFLOW_URL}/api/v2"
