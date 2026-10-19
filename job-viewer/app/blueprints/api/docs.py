from pathlib import Path

from flask import Blueprint, render_template, send_from_directory

api_docs_bp = Blueprint("api_docs", __name__)

_OPENAPI_DIR = Path(__file__).resolve().parents[2] / "static" / "openapi"


@api_docs_bp.route("/api/openapi.yaml", methods=["GET"])
def openapi_spec():
    return send_from_directory(
        _OPENAPI_DIR,
        "v1.yaml",
        mimetype="application/yaml",
        max_age=0,
    )


@api_docs_bp.route("/api/docs", methods=["GET"])
def swagger_ui():
    return render_template("swagger.html")
