"""FITS preview rendering and DS9 region normalization (including WCS)."""

from __future__ import annotations

import math
import re
import struct
import zlib
from pathlib import Path
from typing import Any

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _shape_coords_finite(shape: dict[str, Any]) -> bool:
    """Reject shapes with NaN/Inf so JSON responses stay valid for browsers."""
    keys = ("x", "y", "r", "w", "h")
    for key in keys:
        if key in shape and not _is_finite_number(shape[key]):
            return False
    return _is_finite_number(shape.get("x")) and _is_finite_number(shape.get("y"))


PREVIEW_MAX_DIM = 1200
SKY_FRAMES = {"icrs", "fk5", "fk4", "j2000", "galactic", "ecliptic", "wcs"}
PIXEL_FRAMES = {"physical", "image", "detector", "amplifier", "linear"}

_SHAPE_RE = re.compile(
    r"^(circle|box)\s*\((.+)\)\s*(?:#\s*(.*))?$",
    re.IGNORECASE,
)
_TEXT_RE = re.compile(r"text\s*=\s*\{([^}]*)\}", re.IGNORECASE)
_COLOR_RE = re.compile(r"\bcolor\s*=\s*([^\s]+)", re.IGNORECASE)
_ANGLE_RE = re.compile(
    r"""^(?P<value>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>"|'|d|r|p)?$""",
    re.IGNORECASE,
)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    chunk = chunk_type + data
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk))


def _colormap_lut(name: str) -> np.ndarray:
    """Return Nx3 uint8 LUT. Gray + a few common maps without matplotlib."""
    t = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    name = (name or "gray").lower()
    if name == "gray":
        rgb = np.stack([t, t, t], axis=1)
    elif name == "hot":
        rgb = np.stack(
            [
                np.clip(t * 2.5, 0, 1),
                np.clip(t * 2.5 - 1.0, 0, 1),
                np.clip(t * 4.0 - 3.0, 0, 1),
            ],
            axis=1,
        )
    elif name == "cool":
        rgb = np.stack([t, 1.0 - t, np.ones_like(t)], axis=1)
    elif name == "inferno":
        # Approximate inferno
        rgb = np.stack(
            [
                np.clip(1.5 * t, 0, 1),
                np.clip(1.8 * t - 0.4, 0, 1) * t,
                np.clip(2.0 * t - 1.0, 0, 1),
            ],
            axis=1,
        )
    elif name == "viridis":
        rgb = np.stack(
            [
                np.clip(0.2 + 0.9 * t**1.2, 0, 1) * (0.3 + 0.7 * t),
                np.clip(0.1 + 1.2 * t - 0.3 * t**2, 0, 1),
                np.clip(0.9 - 0.7 * t + 0.2 * t**2, 0, 1),
            ],
            axis=1,
        )
    else:
        rgb = np.stack([t, t, t], axis=1)
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)


def _apply_scale(pixels: np.ndarray, scale: str) -> np.ndarray:
    scale = (scale or "linear").lower()
    positive = np.maximum(pixels, 0)
    if scale == "log":
        return np.log1p(positive)
    if scale == "sqrt":
        return np.sqrt(positive)
    return pixels


def fits_preview_png(
    filename: Path,
    scale: str = "linear",
    colormap: str = "gray",
) -> bytes:
    try:
        raw_data = fits.getdata(filename, 0, memmap=True)
    except ValueError:
        raw_data = fits.getdata(filename, 0, memmap=False)
    if raw_data is None:
        raise ValueError("FITS image has no primary data")
    data = np.asarray(raw_data)
    while data.ndim > 2:
        data = data[0]
    if data.ndim != 2:
        raise ValueError("FITS image must contain a two-dimensional image")

    stride = max(1, int(np.ceil(max(data.shape) / PREVIEW_MAX_DIM)))
    pixels = np.asarray(data[::stride, ::stride], dtype=np.float32)
    finite = np.isfinite(pixels)
    if not finite.any():
        raise ValueError("FITS image contains no finite pixels")

    scaled_vals = _apply_scale(np.nan_to_num(pixels, nan=0.0), scale)
    finite = np.isfinite(scaled_vals)
    low, high = np.percentile(scaled_vals[finite], (1, 99))
    if high <= low:
        idx = np.where(finite, 127, 0).astype(np.uint8)
    else:
        norm = np.clip(
            (scaled_vals - low) * (255.0 / (high - low)),
            0,
            255,
        )
        idx = np.where(finite, norm, 0).astype(np.uint8)

    idx = np.flipud(idx)
    lut = _colormap_lut(colormap)
    rgb = lut[idx]
    height, width, _ = rgb.shape
    rows = b"".join(b"\x00" + row.tobytes() for row in rgb)
    # color type 2 = truecolor RGB
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(rows, level=6))
        + _png_chunk(b"IEND", b"")
    )


def fits_image_shape(path: Path) -> tuple[int, int]:
    with fits.open(path) as hdul:
        header = hdul[0].header
        return int(header.get("NAXIS1", 0)), int(header.get("NAXIS2", 0))


def _header_value_str(value: Any) -> str:
    if value is True:
        return "T"
    if value is False:
        return "F"
    if value is None:
        return ""
    return str(value)


def fits_header_payload(path: Path) -> dict[str, Any]:
    """Return FITS header cards plus a compact WCS summary for client cursor readout."""
    with fits.open(path) as hdul:
        header = hdul[0].header
        naxis1 = int(header.get("NAXIS1", 0) or 0)
        naxis2 = int(header.get("NAXIS2", 0) or 0)
        cards = []
        for card in header.cards:
            key = card.keyword
            if not key or key == "COMMENT" and card.value == "":
                # Keep COMMENT/HISTORY cards; skip fully empty junk
                pass
            cards.append(
                {
                    "key": key,
                    "value": _header_value_str(card.value),
                    "comment": card.comment or "",
                }
            )

        wcs_info: dict[str, Any] = {"available": False}
        try:
            wcs = WCS(header)
            if wcs.naxis >= 2 and wcs.has_celestial:
                celestial = wcs.celestial
                ctype = [str(c) for c in celestial.wcs.ctype]
                crpix = [float(x) for x in celestial.wcs.crpix]
                crval = [float(x) for x in celestial.wcs.crval]
                # Prefer full CD matrix when present
                try:
                    cd = celestial.pixel_scale_matrix.tolist()
                except Exception:
                    cdelt = [float(x) for x in celestial.wcs.cdelt]
                    cd = [[cdelt[0], 0.0], [0.0, cdelt[1]]]
                wcs_info = {
                    "available": True,
                    "ctype": ctype,
                    "crpix": crpix,  # FITS 1-based
                    "crval": crval,  # degrees
                    "cd": cd,  # degrees per pixel
                }
        except Exception as exc:
            wcs_info = {"available": False, "error": str(exc)}

    return {
        "naxis1": naxis1,
        "naxis2": naxis2,
        "cards": cards,
        "wcs": wcs_info,
    }


def discover_reg_files(fits_path: Path) -> list[Path]:
    """Find region files associated with a FITS product."""
    stem = fits_path.name
    for ext in (".fit", ".fits", ".fts", ".FIT", ".FITS", ".FTS"):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
            break

    candidates = [
        fits_path.with_name(stem + ".reg"),
        fits_path.with_name(stem + "_objects.reg"),
        fits_path.with_name(stem + "_refstars.reg"),
        fits_path.with_suffix(".reg"),
    ]
    # Also any sibling *.reg that starts with the stem
    parent = fits_path.parent
    if parent.is_dir():
        for path in sorted(parent.glob(stem + "*.reg")):
            candidates.append(path)

    seen: set[Path] = set()
    result: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        result.append(path)
    return result


def _parse_angle_to_pixels(token: str, wcs: WCS | None, frame: str) -> float:
    token = token.strip()
    match = _ANGLE_RE.match(token)
    if not match:
        return float(token)
    value = float(match.group("value"))
    unit = (match.group("unit") or "p").lower()
    if unit in {"", "p"} or frame in PIXEL_FRAMES:
        if unit in {'"', "'", "d", "r"} and frame in PIXEL_FRAMES:
            # Angular unit with pixel frame — treat numeric as pixels if no WCS
            if wcs is None:
                return value
        elif unit in {"", "p"}:
            return value

    # Convert angular → pixels via WCS
    if wcs is None:
        return value
    scales = wcs.proj_plane_pixel_scales()
    # Astropy may return a Quantity array or a list of Quantities
    if hasattr(scales, "to_value"):
        pixscale_deg = float(np.mean(scales.to_value(u.deg)))
    else:
        pixscale_deg = float(np.mean([s.to_value(u.deg) for s in scales]))
    if unit == '"':
        deg = value / 3600.0
    elif unit == "'":
        deg = value / 60.0
    elif unit == "d":
        deg = value
    elif unit == "r":
        deg = np.degrees(value)
    else:
        return value
    if not _is_finite_number(pixscale_deg) or pixscale_deg <= 0:
        return value
    result = deg / pixscale_deg
    return result if _is_finite_number(result) else value


def _sky_to_pixel(ra_tok: str, dec_tok: str, wcs: WCS, frame: str) -> tuple[float, float]:
    if frame == "galactic":
        coord = SkyCoord(f"{ra_tok} {dec_tok}", unit=(u.deg, u.deg), frame="galactic")
    elif frame in {"fk5", "j2000"}:
        coord = SkyCoord(f"{ra_tok} {dec_tok}", unit=(u.hourangle, u.deg), frame="fk5")
    else:
        # icrs / wcs / default sky
        coord = SkyCoord(f"{ra_tok} {dec_tok}", unit=(u.hourangle, u.deg), frame="icrs")
    x, y = wcs.world_to_pixel(coord)
    fx, fy = float(x), float(y)
    if not (_is_finite_number(fx) and _is_finite_number(fy)):
        raise ValueError("WCS world_to_pixel returned non-finite coordinates")
    return fx, fy


def _parse_shape_args(
    shape: str,
    args_str: str,
    frame: str,
    wcs: WCS | None,
) -> dict[str, Any] | None:
    parts = [p.strip() for p in args_str.split(",")]
    shape = shape.lower()
    try:
        if shape == "circle" and len(parts) >= 3:
            if frame in SKY_FRAMES:
                if wcs is None:
                    return None
                x, y = _sky_to_pixel(parts[0], parts[1], wcs, frame)
                r = _parse_angle_to_pixels(parts[2], wcs, frame)
            else:
                # DS9 image/physical are 1-based
                x = float(parts[0]) - 1.0
                y = float(parts[1]) - 1.0
                r = _parse_angle_to_pixels(parts[2], wcs, frame)
            parsed = {"type": "circle", "x": x, "y": y, "r": r}
            return parsed if _shape_coords_finite(parsed) else None
        if shape == "box" and len(parts) >= 4:
            if frame in SKY_FRAMES:
                if wcs is None:
                    return None
                x, y = _sky_to_pixel(parts[0], parts[1], wcs, frame)
                w = _parse_angle_to_pixels(parts[2], wcs, frame)
                h = _parse_angle_to_pixels(parts[3], wcs, frame)
            else:
                x = float(parts[0]) - 1.0
                y = float(parts[1]) - 1.0
                w = _parse_angle_to_pixels(parts[2], wcs, frame)
                h = _parse_angle_to_pixels(parts[3], wcs, frame)
            parsed = {"type": "box", "x": x, "y": y, "w": w, "h": h}
            return parsed if _shape_coords_finite(parsed) else None
    except Exception:
        return None
    return None


def normalize_reg_content(
    content: str,
    fits_path: Path,
    layer_name: str = "regions",
    default_color: str = "lime",
) -> dict[str, Any]:
    width, height = fits_image_shape(fits_path)
    wcs = None
    wcs_error = None
    try:
        with fits.open(fits_path) as hdul:
            wcs = WCS(hdul[0].header)
            if wcs.naxis < 2:
                wcs = None
    except Exception as exc:
        wcs_error = str(exc)
        wcs = None

    frame = "physical"
    color = default_color
    shapes: list[dict[str, Any]] = []
    skipped = 0

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if lower.startswith("global"):
            color_match = _COLOR_RE.search(line)
            if color_match:
                color = color_match.group(1).strip("'\"")
            continue
        if lower in PIXEL_FRAMES or lower in SKY_FRAMES or lower in {"wcs"}:
            frame = lower
            continue

        match = _SHAPE_RE.match(line)
        if not match:
            skipped += 1
            continue
        shape_type, args_str, comment = match.group(1), match.group(2), match.group(3) or ""
        parsed = _parse_shape_args(shape_type, args_str, frame, wcs)
        if not parsed:
            skipped += 1
            continue
        text_match = _TEXT_RE.search(comment)
        if text_match:
            parsed["text"] = text_match.group(1)
        shape_color = _COLOR_RE.search(comment)
        parsed["color"] = shape_color.group(1).strip("'\"") if shape_color else color
        shapes.append(parsed)

    return {
        "name": layer_name,
        "color": color,
        "width": width,
        "height": height,
        "flipped": True,  # preview uses np.flipud
        "wcs_available": wcs is not None,
        "wcs_error": wcs_error,
        "shapes": shapes,
        "skipped": skipped,
    }


def normalize_structured_region(
    fits_path: Path,
    *,
    shape: str,
    frame: str,
    coords: list[str],
    color: str = "cyan",
    text: str = "",
    layer_name: str = "Custom",
) -> dict[str, Any]:
    """Build a one-shape layer from structured UI input."""
    shape = shape.lower().strip()
    frame = frame.lower().strip()
    if shape == "circle":
        if len(coords) < 3:
            raise ValueError("circle requires x/ra, y/dec, radius")
        line = f"{frame}\ncircle({coords[0]},{coords[1]},{coords[2]})"
    elif shape == "box":
        if len(coords) < 4:
            raise ValueError("box requires x/ra, y/dec, width, height")
        line = f"{frame}\nbox({coords[0]},{coords[1]},{coords[2]},{coords[3]})"
    else:
        raise ValueError(f"unsupported shape: {shape}")
    if text:
        line += f" # text={{{text}}}"
    content = f"global color={color}\n{line}\n"
    return normalize_reg_content(content, fits_path, layer_name=layer_name, default_color=color)
