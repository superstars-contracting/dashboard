"""Local-file-based Google Drive archive.

Google Drive for Desktop syncs a local folder to the cloud. Our job ends at
copying the finalized DCR PDF into the correct local synced folder; Drive
handles the rest. No Google API calls, no OAuth tokens, no rate limits.

Per-project mapping lives in `drive_targets.json` at the dashboard root.
Shape:

    {
      "FR-BX-001": {
        "root":   "G:\\My Drive\\Projects\\890 E 135th Street",
        "slug":   "890-E-135th"
      }
    }

  - `root`: absolute path to the project's top-level folder inside the local
            Drive mount. The DCR archive lands at `<root>\\Daily Reports`.
            Future surfaces extend off `<root>` similarly (Certificate of
            Fitness Cards, Workers, etc.) — keep them in one place.
  - `slug`: short human-readable identifier baked into the archive filename
            (e.g. `890-E-135th`). Falls back to a slugified project name if
            unset.

If a mapping is missing OR `root` doesn't exist on disk OR `Daily Reports`
can't be created, the archive call returns `{"ok": False, "status":
"unavailable", ...}` and the caller treats it as a WARN, not an error. The
local PDF (under `data_room/reports/dcr/...`) is always the source of
truth; Drive is convenience.
"""
import json
import logging
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TARGETS_FILE = SCRIPT_DIR / "drive_targets.json"


def load_drive_targets():
    """Return the project->target mapping, or {} if the file is missing
    or unreadable. Never raises — Drive archive is non-blocking."""
    if not TARGETS_FILE.exists():
        return {}
    try:
        return json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logging.warning(f"drive_targets.json unreadable: {e}")
        return {}


def archive_dcr_pdf(pdf_path, project_code, report_date, sequence,
                    audience="internal", targets=None):
    """Copy a finalized DCR PDF into the project's Drive-synced Daily Reports
    folder. Idempotent: re-finalizing the same (project, sequence) overwrites
    the same filename in Drive.

    Returns dict:
      {"ok": True,  "drive_path": "<abs>", "filename": "..."}
      {"ok": False, "status": "unavailable", "reason": "..."}  ← warn, not error
      {"ok": False, "status": "error",       "reason": "..."}

    The caller surfaces all three to the operator UI; only `status=error`
    should ever block downstream steps. `status=unavailable` is the expected
    state when Drive for Desktop isn't running yet — finalize still succeeds.
    """
    targets = targets if targets is not None else load_drive_targets()
    cfg = targets.get(project_code) or {}
    root = cfg.get("root")
    if not root:
        return {"ok": False, "status": "unavailable",
                "reason": f"No drive_targets entry for {project_code} (or 'root' unset). "
                          f"Local PDF retained at {pdf_path}."}

    root_path = Path(root)
    if not root_path.exists():
        return {"ok": False, "status": "unavailable",
                "reason": f"Drive root {root_path} does not exist on disk. "
                          f"Is Google Drive for Desktop running? "
                          f"Local PDF retained at {pdf_path}."}

    dst_dir = root_path / "Daily Reports"
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "status": "error",
                "reason": f"Cannot create {dst_dir}: {e}"}

    slug = cfg.get("slug") or _slugify(project_code) or project_code
    filename = f"DCR-{project_code}-{sequence:03d}_{report_date}_{slug}_{audience}.pdf"
    dst = dst_dir / filename

    src = Path(pdf_path)
    if not src.exists():
        return {"ok": False, "status": "error",
                "reason": f"Source PDF missing: {src}"}
    try:
        shutil.copy2(src, dst)  # overwrites if exists — idempotent re-issue
    except Exception as e:
        return {"ok": False, "status": "error",
                "reason": f"Copy failed {src} -> {dst}: {e}"}

    return {"ok": True, "drive_path": str(dst), "filename": filename}


def _slugify(s, fallback="project"):
    import re
    if not s:
        return fallback
    out = re.sub(r"[^A-Za-z0-9 _-]", "", str(s))
    out = re.sub(r"\s+", "-", out).strip("-_")
    return out or fallback
