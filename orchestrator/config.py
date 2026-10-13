from collections import defaultdict
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

FILE_DIR = os.path.expanduser(os.environ.get("FILE_DIR", "~/processed_images"))
APEX_CONF_FOLDER = os.path.expanduser(os.environ.get("APEX_CONF_FOLDER", "~/.Apex/"))
APEX_PYTHON_PATH = os.path.expanduser(os.environ.get("APEX_PYTHON_PATH", "~/apex/bin/python"))

# job-viewer status callback (no trailing slash). Empty endpoint disables callbacks.
# Token must match job-viewer JOBVIEWER_CALLBACK_TOKEN.
JOBVIEWER_ENDPOINT = os.environ.get(
    "JOBVIEWER_ENDPOINT", "http://localhost:5000/api/jobs/update"
)
JOBVIEWER_TOKEN = os.environ.get(
    "JOBVIEWER_CALLBACK_TOKEN", os.environ.get("JOBVIEWER_TOKEN", "token")
)

# Focal length (mm) for apex_hedit, keyed by job-viewer telescope id.
FOCAL_LENGTH_MM = {
    "abao_as32": 2141,
    # mondy_azt33ik: unknown / set when confirmed
}

# Config file names
APEX_CONF_FILES = {
    "abao_as32": "abao_as32.conf",
    "mondy_azt33ik": "apex_mondy.conf",
}

# Apex configuration overrides for each telescope.
APEX_CONF_OVERRIDES_STACK = defaultdict(str, {
    "abao_as32": "extraction.threshold=50",
    "mondy_azt33ik": "extraction.threshold=10",
})  
APEX_CONF_OVERRIDES_QC = defaultdict(str, {
    "abao_as32": "extraction.threshold=50",
    "mondy_azt33ik": "extraction.threshold=10",
})
APEX_CONF_OVERRIDES_AUTO = defaultdict(str, {
    "abao_as32": "extraction.threshold=3 identification.preferred_algorithms=triangle_fs,triangle_si identification.search_step=10 identification.max_objects=150",
    "mondy_azt33ik": "extraction.threshold=3 identification.preferred_algorithms=dist-orient identification.search_step=10 identification.max_objects=30",
})
APEX_CONF_OVERRIDES_CALIBRATE = defaultdict(str, {
    "abao_as32": "extraction.threshold=50",
    "mondy_azt33ik": "extraction.threshold=10",
})