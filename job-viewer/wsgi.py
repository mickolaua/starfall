"""WSGI entrypoint for the MVC job-viewer app."""

from pathlib import Path
import sys

# Ensure job-viewer/ is on sys.path so ``app``, ``config``, and ``fits_viewer``
# resolve whether Flask loads this as ``wsgi`` or ``job-viewer.wsgi``.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app import create_app

app = create_app()
