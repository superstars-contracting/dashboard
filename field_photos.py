#!/usr/bin/env python3
"""Field-photo image processing (#235, Phase 1).

For each uploaded image: read EXIF (DateTimeOriginal -> taken_at LOCAL;
Orientation -> baked into the pixels so sideways iPhone shots display UPRIGHT),
downscale to a display image (long edge ~2000px) + a thumbnail (~400px), and
re-save as JPEG WITHOUT EXIF — which strips GPS / camera metadata (privacy) and
the now-applied orientation. HEIC/HEIF decode via pillow_heif.

A file that can't be decoded raises SkipImage(reason) so the caller records it
and KEEPS GOING — one bad photo never fails a whole batch. PURE (no DB, no
Flask, no disk): the endpoint feeds bytes in and writes the returned bytes out.
"""
import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

# Pillow's decompression-bomb guard is fine for field photos (a 48MP phone shot
# is ~48M px, well under the default ~178M-px limit). Leave it on.

DISPLAY_LONG_EDGE = 2000          # downscaled display image
THUMB_LONG_EDGE = 400             # grid thumbnail
DISPLAY_QUALITY = 85
THUMB_QUALITY = 80
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
MAX_FILE_BYTES = 30 * 1024 * 1024  # per-file cap (skip with reason if larger)

_TAG_DATETIME_ORIGINAL = 36867     # EXIF DateTimeOriginal (in the Exif sub-IFD)
_TAG_DATETIME = 306                # base IFD DateTime (fallback)
_TAG_ORIENTATION = 274
_EXIF_IFD = 0x8769

_HEIF_OK = None


class SkipImage(Exception):
    """One file couldn't be processed — caller records {file, reason} + continues."""


def _ensure_heif():
    """Register the HEIF opener once. Returns True if HEIC decoding is available."""
    global _HEIF_OK
    if _HEIF_OK is None:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            _HEIF_OK = True
        except Exception:
            _HEIF_OK = False
    return _HEIF_OK


def _exif_taken_at(im):
    """LOCAL 'YYYY-MM-DD HH:MM:SS' from EXIF DateTimeOriginal (or DateTime), else
    None. EXIF timestamps are camera wall-clock — already LOCAL, no TZ math (so no
    UTC off-by-one). We just reformat the 'YYYY:MM:DD HH:MM:SS' separators."""
    try:
        exif = im.getexif()
    except Exception:
        return None
    if not exif:
        return None
    raw = None
    try:
        ifd = exif.get_ifd(_EXIF_IFD)
        if ifd:
            raw = ifd.get(_TAG_DATETIME_ORIGINAL)
    except Exception:
        raw = None
    if not raw:
        raw = exif.get(_TAG_DATETIME_ORIGINAL)   # some writers put it in the base IFD
    if not raw:
        raw = exif.get(_TAG_DATETIME)            # DateTime fallback
    if not raw:
        return None
    raw = str(raw).strip().replace("\x00", "")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _orientation(im):
    try:
        o = im.getexif().get(_TAG_ORIENTATION)
        return int(o) if o else 1
    except Exception:
        return 1


def process_image(data_bytes, filename, fallback_dt_iso=None):
    """Decode + orientation-correct + downscale + thumbnail ONE image, stripping
    GPS/EXIF from the stored bytes. Returns:
      { display_bytes, thumb_bytes, mime, ext, width, height,
        taken_at, taken_at_estimated, orientation_applied, file_name }
    Raises SkipImage(reason) if the file can't be decoded/processed."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise SkipImage(f"unsupported file type {ext or '(none)'}")
    if data_bytes is None or len(data_bytes) == 0:
        raise SkipImage("empty file")
    if len(data_bytes) > MAX_FILE_BYTES:
        raise SkipImage(f"file too large ({len(data_bytes) // (1024 * 1024)} MB; max {MAX_FILE_BYTES // (1024 * 1024)} MB)")
    if ext in (".heic", ".heif") and not _ensure_heif():
        raise SkipImage("HEIC not supported on this server")

    try:
        im = Image.open(io.BytesIO(data_bytes))
        im.load()
    except Exception as e:
        raise SkipImage(f"could not decode image ({type(e).__name__})")

    # EXIF date + orientation must be read BEFORE exif_transpose (which clears it)
    taken_at = _exif_taken_at(im)
    estimated = False
    if not taken_at:
        taken_at = fallback_dt_iso or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        estimated = True
    orientation_applied = _orientation(im) != 1

    try:
        im = ImageOps.exif_transpose(im)   # bake orientation into the pixels -> upright
    except Exception:
        pass
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")

    # Display image: downscale (no EXIF on save -> GPS/orientation stripped)
    disp = im.copy()
    disp.thumbnail((DISPLAY_LONG_EDGE, DISPLAY_LONG_EDGE), Image.LANCZOS)
    dbuf = io.BytesIO()
    disp.save(dbuf, "JPEG", quality=DISPLAY_QUALITY, optimize=True)

    # Thumbnail
    th = im.copy()
    th.thumbnail((THUMB_LONG_EDGE, THUMB_LONG_EDGE), Image.LANCZOS)
    tbuf = io.BytesIO()
    th.save(tbuf, "JPEG", quality=THUMB_QUALITY, optimize=True)

    return {
        "display_bytes": dbuf.getvalue(),
        "thumb_bytes": tbuf.getvalue(),
        "mime": "image/jpeg",
        "ext": ".jpg",
        "width": disp.width,
        "height": disp.height,
        "taken_at": taken_at,
        "taken_at_estimated": estimated,
        "orientation_applied": orientation_applied,
        "file_name": Path(filename or "photo").name,
    }
