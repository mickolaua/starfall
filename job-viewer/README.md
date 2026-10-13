# Job Viewer

Flask UI for submitting image-processing jobs and viewing results.

## Entrypoints

Two apps share the same `config.py`, templates, static files, and database.

| App | Entrypoint | Notes |
|-----|------------|--------|
| **Legacy** (default) | `run_app.py` | Monolithic module; default via `.flaskenv` |
| **MVC** | `wsgi.py` | Application factory + blueprints under `app/` |

### Run legacy (default)

```bash
cd job-viewer
source .venv/bin/activate   # if using venv
flask run                   # uses FLASK_APP=run_app.py from .flaskenv
# or:
flask --app run_app run
```

### Run MVC

```bash
cd job-viewer
source .venv/bin/activate
flask --app wsgi run
# or:
FLASK_APP=wsgi:app flask run
```

Do not run both in the same process. Point Prefect callbacks at whichever app is listening.
