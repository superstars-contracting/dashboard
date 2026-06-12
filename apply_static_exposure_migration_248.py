"""#248 — one-time data migration for the static-exposure fix. Idempotent.

The serving change (#248) moved generated artifacts from the public /files/
mount to the gated /project-files/ route. Two places persist the OLD URL
scheme and need a rewrite:

  1. photos.url rows ('/files/data_room/photos/...') — consumed by the DCR
     entry view and baked into DCR renders by render_dcr_html.
  2. Already-rendered artifact HTML on disk (DCR renders, credential card
     exports, legacy root outputs) embedding src/href="/files/..." image and
     link references.

/files/static/... references are left untouched — the vendored-asset mount
keeps that URL shape (public by design).

Idempotent: a second run finds nothing left to rewrite and reports 0s.
PII discipline: prints counts per top-level directory only — never filenames
(credential export names embed employee ids; keep them out of scrollback).

Run:  python apply_static_exposure_migration_248.py
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"

# (src|href)="/files/..." -> /project-files/..., except /files/static/.
_URL_RE = re.compile(r'(src|href)=(["\'])/files/(?!static/)')

# Where rendered artifacts live. Source-template dirs (forms_source,
# signage_source, ...) are deliberately absent — they aren't served.
SWEEP_DIRS = [
    SCRIPT_DIR / "data_room",
    SCRIPT_DIR / "meetings",
    SCRIPT_DIR / "drop_plans",
    SCRIPT_DIR / "site_closures",
    SCRIPT_DIR / "toolbox_talks",
    SCRIPT_DIR / "meeting_workflow_run",
    SCRIPT_DIR / "rfi_workflow_run",
]


def migrate_photo_urls() -> int:
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    try:
        cur = conn.execute(
            "UPDATE photos SET url = REPLACE(url, '/files/', '/project-files/') "
            "WHERE url LIKE '/files/%' AND url NOT LIKE '/files/static/%'"
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def sweep_artifact_html() -> Counter:
    counts: Counter = Counter()
    targets = list(SCRIPT_DIR.glob("*.html"))
    for d in SWEEP_DIRS:
        if d.exists():
            targets.extend(p for p in d.rglob("*.html") if p.is_file())
    for p in targets:
        try:
            txt = p.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            continue
        new_txt, n = _URL_RE.subn(r"\1=\2/project-files/", txt)
        if n:
            p.write_text(new_txt, encoding="utf-8")
            rel = p.relative_to(SCRIPT_DIR)
            top = rel.parts[0] if len(rel.parts) > 1 else "(root)"
            counts[top] += 1
    return counts


def main() -> None:
    rows = migrate_photo_urls()
    print(f"photos.url rows rewritten to /project-files/: {rows}")
    counts = sweep_artifact_html()
    total = sum(counts.values())
    print(f"artifact HTML files rewritten: {total}")
    for top, n in sorted(counts.items()):
        print(f"  {top}: {n}")
    if rows == 0 and total == 0:
        print("nothing to do — already migrated (idempotent re-run).")


if __name__ == "__main__":
    main()
