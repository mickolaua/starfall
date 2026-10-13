"""Prefect image-processing pipeline (calibrate → QC → stack → auto)."""

from __future__ import annotations

import shlex
from pathlib import Path
import sys
from typing import Any

import requests
from prefect import flow, get_run_logger, task
from prefect.client.schemas import State
from prefect.context import get_run_context
from prefect_shell import ShellOperation
from prefect.blocks.system import Secret
from prefect.variables import Variable

sys.path.append(str(Path(__file__).parent.parent))

import config


# Get variables once at the beginning
JOBVIEWER_ENDPOINT = Variable.get("jobviewer_endpoint").get("url")
if not JOBVIEWER_ENDPOINT:
    raise ValueError("Jobviewer endpoint not found")
JOBVIEWER_TOKEN = Secret.load("jobviewer-callback-token").get()
if not JOBVIEWER_TOKEN:
    raise ValueError("Jobviewer callback token not found")
APEX_SETTINGS = Variable.get("apex_settings")
if not APEX_SETTINGS:
    raise ValueError("Apex settings not found")
APEX_FOLDER = APEX_SETTINGS.get("apex_folder")
if not APEX_FOLDER:
    raise ValueError("Apex folders not found")
APEX_PYTHON_PATH = APEX_SETTINGS.get("python_path")
if not APEX_PYTHON_PATH:
    raise ValueError("Apex python path not found")


def _catalog_id_to_options(astrometric_catalog: str, photometric_catalog: str) -> str:
    options = set()
    if astrometric_catalog == "usnob":
        options.add("catalog.usno_reader.usnob_astrometric_priority=99")
        options.add("catalog.usno_reader.usnob_allow_remote=1")
    elif astrometric_catalog == "ps1":
        options.add("catalog.ps1_reader.astrometric_priority=99")
        options.add("catalog.ps1_reader.allow_remote=1")
    elif astrometric_catalog == "sdss_dr12":
        options.add("catalog.sdss_reader.sdss_dr12_astrometric_priority=99")
        options.add("catalog.sdss_reader.sdss_dr12_allow_remote=1")
    elif astrometric_catalog == "gaia_edr3":
        options.add("catalog.gaia_reader.gaia_edr3_astrometric_priority=99")
        options.add("catalog.gaia_reader.gaia_edr3_allow_remote=1")
    elif astrometric_catalog == "twomass":
        options.add("catalog.twomass_reader.astrometric_priority=99")
        options.add("catalog.twomass_reader.allow_remote=1")
    
    if photometric_catalog == "usnob":
        options.add("catalog.usno_reader.usnob_photometric_priority=99")
        options.add("catalog.usno_reader.usnob_allow_remote=1")
    elif photometric_catalog == "ps1":
        options.add("catalog.ps1_reader.photometric_priority=99")
        options.add("catalog.ps1_reader.allow_remote=1")
    elif photometric_catalog == "sdss_dr12":
        options.add("catalog.sdss_reader.sdss_dr12_photometric_priority=99")
        options.add("catalog.sdss_reader.sdss_dr12_allow_remote=1")
    elif photometric_catalog == "gaia_edr3":
        options.add("catalog.gaia_reader.gaia_edr3_photometric_priority=99")
        options.add("catalog.gaia_reader.gaia_edr3_allow_remote=1")
    elif photometric_catalog == "twomass":
        options.add("catalog.twomass_reader.photometric_priority=99")
        options.add("catalog.twomass_reader.allow_remote=1")
    return " ".join(options)


def _apex_env(telescope: str | None) -> dict[str, str]:
    conf_name = config.APEX_CONF_FILES.get(telescope, "apex.conf")
    return {"APEXCONF": str(Path(APEX_FOLDER) / conf_name)}


def _shell_join(paths: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in paths)


def _as_rel_or_abs(working_dir: Path, path: str) -> str:
    """Prefer paths relative to working_dir when possible (matches Apex @file usage)."""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(working_dir.resolve()))
    except ValueError:
        return str(p)


@task(name="prepare")
def prepare(
    working_dir: str,
    light_filenames: list[str],
    dark_filenames: list[str] | None = None,
    flat_filenames: list[str] | None = None,
    telescope: str | None = None,
    ra_field: Any = None,
    dec_field: Any = None,
) -> None:
    """
    Telescope-specific preparation steps.
    """
    logger = get_run_logger()
    
    wd = Path(working_dir)

    py = shlex.quote(APEX_PYTHON_PATH)

    telescope = telescope or ""
    if telescope != "mondy_azt33ik":
        if not ra_field or not dec_field:
            raise ValueError(f"ra_field and dec_field are required for {telescope}")

        if telescope == "abao_as32":
            hedit_fields = f"FOC_LEN=2141;FOCALLEN=2141;"
        else:
            hedit_fields = ""

        if hedit_fields:
            ShellOperation(
                commands=[
                    f"{py} -m apex.scripts.apex_hedit "
                    f"{_shell_join(light_filenames)} {_shell_join(dark_filenames)} {_shell_join(flat_filenames)} action=edit fields={hedit_fields}"
                ],
                working_dir=str(wd),
                env=_apex_env(telescope),
            ).run()

        ra = str(ra_field)
        dec = str(dec_field)

        commands = [
            f"{py} -m apex.scripts.wcs_hedit {_shell_join(light_filenames)} pixsize_unit=mm "
            f"object_ra={shlex.quote(ra)} object_dec={shlex.quote(dec)}"
        ]


        ShellOperation(
            commands=commands,
            working_dir=str(wd),
            env=_apex_env(telescope),
        ).run()


@task(name="calibrate_images")
def calibrate_images(
    working_dir: str,
    light_filenames: list[str],
    dark_filenames: list[str] | None = None,
    flat_filenames: list[str] | None = None,
    telescope: str | None = None,
) -> list[str]:
    """
    Run apex_calibrate. Lights-only jobs use dark=0/flat=0 (still apply sky etc.).
    Returns absolute paths to calibrated light frames under lights/.
    """
    logger = get_run_logger()
    if not light_filenames:
        logger.warning("No light filenames; skipping calibration")
        return []

    wd = Path(working_dir)
    wd.mkdir(parents=True, exist_ok=True)
    dark_filenames = dark_filenames or []
    flat_filenames = flat_filenames or []

    parts: list[str] = []
    if dark_filenames:
        parts.append("dark=1 util.automation.calibration.dark_dir=./darks/")
    else:
        parts.append("dark=0")

    if flat_filenames:
        parts.append("flat=1 util.automation.calibration.flat_dir=./flats/")
    else:
        parts.append("flat=0")

    parts.append("sky=1 cosmics=0")
    calib_args = " ".join(parts)

    # Pass basenames/relpaths when files live under working_dir
    lights = [_as_rel_or_abs(wd, f) for f in light_filenames]

    ShellOperation(
        commands=[
            f"{shlex.quote(APEX_PYTHON_PATH)} -m apex.scripts.apex_calibrate "
            f"{_shell_join(lights)} {calib_args} {config.APEX_CONF_OVERRIDES_CALIBRATE.get(telescope, '')}"
        ],
        working_dir=str(wd),
        env=_apex_env(telescope),
    ).run()

    calibrated = sorted((wd / "lights").glob("*calibrated*"))
    if not calibrated:
        calibrated = sorted((wd / "light").glob("*calibrated*"))
    calibrated_paths = [str(p.resolve()) for p in calibrated if p.is_file()]

    # # If Apex wrote next to inputs with .calibrated.fit suffix, pick those up too
    # if not calibrated_paths:
    #     for light in light_filenames:
    #         cand = Path(light).with_suffix("").as_posix() + ".calibrated.fit"
    #         # with_suffix only strips last suffix; lights are often .fit
    #         stem = Path(light)
    #         alt = stem.parent / (stem.stem + ".calibrated.fit")
    #         if alt.is_file():
    #             calibrated_paths.append(str(alt.resolve()))

    logger.info("Calibrated frames: %s", calibrated_paths)
    return calibrated_paths


@task(name="quality_control")
def quality_control(
    working_dir: str,
    light_filenames: list[str],
    telescope: str | None = None,
) -> list[str]:
    logger = get_run_logger()
    if not light_filenames:
        logger.warning("No frames for QC; skipping")
        return []

    wd = Path(working_dir)
    wd.mkdir(parents=True, exist_ok=True)
    frames = [_as_rel_or_abs(wd, f) for f in light_filenames]

    ShellOperation(
        commands=[
            f"{shlex.quote(APEX_PYTHON_PATH)} -m apex.scripts.apex_qc "
            f"{_shell_join(frames)} {config.APEX_CONF_OVERRIDES_QC.get(telescope, '')}"
        ],
        working_dir=str(wd),
        env=_apex_env(telescope),
    ).run()

    good_path = wd / "good_frames.txt"
    if not good_path.is_file():
        logger.warning("good_frames.txt missing after QC")
        return []
    lines = [ln.strip() for ln in good_path.read_text().splitlines() if ln.strip()]
    logger.info("Good frames (%d): %s", len(lines), lines)
    return lines


@task(name="stack_images")
def stack_images(
    working_dir: str,
    stack_mode: str,
    telescope: str | None = None,
) -> None:
    logger = get_run_logger()
    if not stack_mode or stack_mode == "none":
        logger.info("Stacking skipped (stack_mode=%r)", stack_mode)
        return

    wd = Path(working_dir)
    good_path = wd / "good_frames.txt"
    if not good_path.is_file():
        logger.warning("No good_frames.txt found; skipping stacking")
        return

    ShellOperation(
        commands=[
            f"{shlex.quote(APEX_PYTHON_PATH)} -m apex.scripts.apex_stack "
            f"@good_frames.txt stack_mode={shlex.quote(stack_mode)} "
            f"extraction.extractor=conn_sep"
        ],
        working_dir=str(wd),
        env=_apex_env(telescope),
    ).run()
    logger.info("Stacking finished (mode=%s)", stack_mode)


@task(name="auto_pipeline")
def auto_pipeline(
    working_dir: str,
    target_files: list[str],
    telescope: str | None = None,
    ra_field: Any = None,
    dec_field: Any = None,
    astrometric_catalog: str | None = None,
    photometric_catalog: str | None = None
    
) -> None:
    """WCS header edit + apex_auto (photometry / identification)."""
    logger = get_run_logger()

    wd = Path(working_dir)
    wd.mkdir(parents=True, exist_ok=True)

    if not target_files:
        light_arg = "."
    else:
        light_arg = _shell_join([_as_rel_or_abs(wd, f) for f in target_files])

    py = shlex.quote(APEX_PYTHON_PATH)
    commands: list[str] = []

    commands.append(
        f"{py} -m apex.scripts.apex_auto {light_arg} "
        f"io.fits_fmt.bitpix=FLOAT {config.APEX_CONF_OVERRIDES_AUTO.get(telescope, '')}"
        f"extraction.noise_mode=local multistage=1 stages=3  "
        f"calibration.background.default_estimator=median "
        f"calibration.params.sat_level=9999999999999 overwrite_frame=1 "
        f"{_catalog_id_to_options(astrometric_catalog, photometric_catalog)}"
    )

    logger.debug("auto_pipeline commands: %r", commands)

    ShellOperation(
        commands=commands,
        working_dir=str(wd),
        env=_apex_env(telescope),
    ).run()
    logger.info("auto_pipeline finished")


def _notify_job_viewer(status: str) -> None:
    try:
        ctx = get_run_context()
        job_id = ctx.flow_run.name if ctx and ctx.flow_run else None
        if not job_id:
            return
        url = f"{JOBVIEWER_ENDPOINT.rstrip('/')}/{job_id}"
        headers = {"Content-Type": "application/json"}
        headers["Authorization"] = f"Bearer {JOBVIEWER_TOKEN}"
        headers["X-JobViewer-Token"] = JOBVIEWER_TOKEN
        response = requests.post(
            url, json={"status": status}, headers=headers, timeout=10
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    except Exception as exc:
        # Never fail the flow because of a callback glitch
        try:
            get_run_logger().warning("job-viewer callback failed: %s", exc)
        except Exception:
            print(f"job-viewer callback failed: {exc}")


def _on_completion(flow, flow_run, state: State) -> None:
    _notify_job_viewer("SUCCESS")


def _on_failure(flow, flow_run, state: State) -> None:
    _notify_job_viewer("FAILED")


@flow(
    log_prints=True,
    on_completion=[_on_completion],
    on_failure=[_on_failure],
)
def image_processing(
    working_dir: str,
    light_filenames: list[str] | None = None,
    dark_filenames: list[str] | None = None,
    flat_filenames: list[str] | None = None,
    telescope: str | None = None,
    stack_mode: str | None = None,
    group_frames: Any = None,
    group_frames_value: Any = None,
    band: str | None = None,
    astrometric_catalog: str | None = None,
    photometric_catalog: str | None = None,
    transient_circle: str | None = None,
    ra_field: Any = None,
    dec_field: Any = None,
    apex_conf: str | None = None,
    options: dict | None = None,
):
    """
    Full image-processing pipeline aligned with the Airflow process_image DAG.

    Parameters mirror the job-viewer /submit payload.
    """
    logger = get_run_logger()
    opts = options or {}
    stack_mode = stack_mode or opts.get("stack_mode") or "none"
    group_frames = group_frames if group_frames is not None else opts.get("group_frames")
    group_frames_value = (
        group_frames_value if group_frames_value is not None else opts.get("group_frames_value")
    )
    band = band or opts.get("filter") or opts.get("band")
    astrometric_catalog = astrometric_catalog or opts.get("astrometric_catalog")
    photometric_catalog = photometric_catalog or opts.get("photometric_catalog")
    transient_circle = transient_circle or opts.get("transient_circle")
    ra_field = ra_field if ra_field is not None else opts.get("ra_field")
    dec_field = dec_field if dec_field is not None else opts.get("dec_field")
    apex_conf = apex_conf or opts.get("apex_conf")
    telescope = telescope or opts.get("telescope")

    lights = list(light_filenames or [])
    darks = list(dark_filenames or [])
    flats = list(flat_filenames or [])
    need_calib = bool(darks or flats)
    need_series = len(lights) > 1

    logger.info(
        "image_processing start: telescope=%r stack_mode=%r band=%r "
        "lights=%d darks=%d flats=%d need_calib=%s need_series=%s "
        "astrometric=%r photometric=%r transient=%r",
        telescope,
        stack_mode,
        band,
        len(lights),
        len(darks),
        len(flats),
        need_calib,
        need_series,
        astrometric_catalog,
        photometric_catalog,
        transient_circle,
    )
    
    prepare(working_dir, lights, darks, flats, telescope, ra_field, dec_field)

    if need_calib:
        calibrated = calibrate_images(working_dir, lights, darks, flats, telescope)
        if not calibrated:
            # Apex naming: <stem>.calibrated.fit beside inputs
            calibrated = [
                str(Path(f).with_name(Path(f).stem + ".calibrated.fit"))
                for f in lights
            ]
            calibrated = [p for p in calibrated if Path(p).is_file()]
        frames_for_qc = calibrated
    else:
        # Lights-only: still run calibrate with dark=0/flat=0 for sky/cosmetics,
        # then fall back to originals if no calibrated products appear.
        calibrated = calibrate_images(working_dir, lights, [], [], telescope)
        frames_for_qc = calibrated if calibrated else lights

    good_frames: list[str] = []
    if need_series and frames_for_qc:
        good_frames = quality_control(working_dir, frames_for_qc, telescope)
        stack_images(working_dir, stack_mode, telescope)
    elif frames_for_qc:
        logger.info("Single-frame job; skipping quality control and stacking")

    # Auto: stacked product preferred when stacking ran; else calibrated / lights
    if need_series and stack_mode and stack_mode != "none":
        wd = Path(working_dir)
        stacked = sorted(
            {
                *wd.glob(f"*.calibrated.*-{stack_mode}.fit"),
                *wd.glob(f"*-{stack_mode}.fit"),
            }
        )
        auto_targets = [str(p.resolve()) for p in stacked if p.is_file()]
        if not auto_targets:
            auto_targets = good_frames or frames_for_qc
    else:
        auto_targets = frames_for_qc

    auto_pipeline(
        working_dir,
        auto_targets,
        telescope,
        ra_field,
        dec_field,
        astrometric_catalog,
        photometric_catalog,
    )

    # Params reserved for later apex flags (catalogs / transient search)
    _ = (group_frames, group_frames_value, apex_conf)


if __name__ == "__main__":
    image_processing.serve(name="Image-Processing")
