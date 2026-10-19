# Job Viewer

Flask UI for submitting image-processing jobs and viewing results.

Versioning and releases (Conventional Commits, tags like `job-viewer-vX.Y.Z`,
Release Please PRs) are documented in [docs/VERSIONING.md](../docs/VERSIONING.md).

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
flask --app wsgi db upgrade   # apply Alembic migrations (job columns, etc.)
flask --app wsgi run
# or:
FLASK_APP=wsgi:app flask run
```

Schema changes for the MVC app are managed with **Flask-Migrate** (`migrations/`). After pulling new revisions, run `flask --app wsgi db upgrade` before starting the server.

Do not run both apps in the same process. Point Prefect callbacks at whichever app is listening.

## API surfaces

| Prefix | Audience | Auth |
|--------|----------|------|
| `/api/v1/...` | User clients / scripts | Session cookie **or** `Authorization: Bearer <user_api_token>` |
| `/api/jobs/...` | Job artifacts (results, preview, …) | Same dual auth |
| `/api/internal/...`, `/api/jobs/update/...` | Prefect/workers | Shared `JOBVIEWER_CALLBACK_TOKEN` only |

Interactive OpenAPI (Swagger UI) for `/api/v1`: **[/api/docs](/api/docs)** — machine-readable spec at [`/api/openapi.yaml`](/api/openapi.yaml).

Create or rotate a user token from **Profile → Account Settings → API Token**, or:

```bash
# After logging in via the browser (session cookie), or with an existing Bearer token:
curl -s -X POST http://127.0.0.1:5000/api/v1/auth/token \
  -H "Authorization: Bearer $TOKEN"
# → { "token": "....", ... }  # save once
```

### Client job flow

```bash
export TOKEN='prefix.secret...'
export BASE='http://127.0.0.1:5000'

# 1) Upload frames
curl -s -X POST "$BASE/api/v1/jobs/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F 'lights=@/path/to/light.fits' \
  -F 'darks=@/path/to/dark.fits' \
  -F 'flats=@/path/to/flat.fits'
# → { "subid", "working_dir", "light_filenames", ... }

# 2) Start processing (same JSON fields as web UI POST /submit)
curl -s -X POST "$BASE/api/v1/jobs" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "subid": "<subid from upload>",
    "working_dir": "<working_dir>",
    "light_filenames": ["..."],
    "dark_filenames": [],
    "flat_filenames": [],
    "name": "optional friendly label",
    "telescope": "mondy_azt33ik",
    "stack_mode": "average",
    "filter": "clear",
    "astrometric_catalog": "gaia_edr3",
    "photometric_catalog": "gaia_edr3"
  }'

# Optional: rename later
curl -s -X PATCH "$BASE/api/v1/jobs/<subid>" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name": "new label"}'

# 3) Poll status (job_status, started_at, finished_at, parameters)
curl -s "$BASE/api/v1/jobs/<subid>" -H "Authorization: Bearer $TOKEN"

# 4) List jobs / fetch results
curl -s "$BASE/api/v1/jobs" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/api/jobs/<subid>/results" -H "Authorization: Bearer $TOKEN"
```

Revoke: `curl -X DELETE "$BASE/api/v1/auth/token" -H "Authorization: Bearer $TOKEN"`.

Job lifecycle `status` is stored only on the `job.status` column (never inside `job_parameters` JSON). Submit parameters are stored in `job_parameters`; `started_at` / `finished_at` are updated when the job is created and when it reaches a terminal state.
