"""#287 (Cloud M1) — THE data-path resolver. One configurable root for every file
the app reads or writes.

    SSC_DATA_ROOT unset  ->  exactly today's workstation layout, byte for byte
                             (every helper returns the same path the old inline
                             SCRIPT_DIR joins produced). ZERO behavior change.
    SSC_DATA_ROOT set    ->  every DATA category resolves under it:
                             <root>/data_room/field_photos, <root>/worker_records,
                             <root>/superstars.db, ...

Static assets and code stay repo-relative — ONLY DATA moves. The categories:

    media    data_room/{field_photos,project_docs,photos,receipts,walkthroughs,
             estimate_docs,material_slips} + worker_records/ + employee_photos/
             + issuer_signatures/
    renders  data_room/{reports,credentials,forms,toolbox_talks,signage}
             + cof_exports/ + the legacy root output dirs (meetings, drop_plans,
             site_closures, toolbox_talks, meeting_workflow_run, rfi_workflow_run)
    logs     server.log (+ data_room/server_logs, written by the launcher)
    db       superstars.db (SQLite default; SSC_DB_URL still rules Postgres)

STORED-PATH REALITY (why resolve_data_path exists): every *_path row written
before #287 is an ABSOLUTE Windows path. Those rows are not rewritten. Reads go
through resolve_data_path(), which serves an absolute path as-is when it still
exists (the workstation today) and otherwise RE-ANCHORS it by its category
suffix under the active root (the cloud disk tomorrow). New media writes store
RELATIVE paths (store_rel) so rows written from #287 on are portable as-is.

Env is read PER CALL, never cached at import: a test server booted with the var
set and one booted without must disagree — and nothing else in the process may
remember the other's answer.
"""
from __future__ import annotations

import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# Every top-level directory name that is DATA. A stored absolute path is
# re-anchored at the FIRST occurrence of one of these in its parts; anything
# not under an anchor is not data and never re-roots.
DATA_ANCHORS = (
    "data_room", "worker_records", "employee_photos", "issuer_signatures",
    "cof_exports", "meetings", "drop_plans", "site_closures", "toolbox_talks",
    "meeting_workflow_run", "rfi_workflow_run",
)


def data_root() -> Path:
    """The active data root: SSC_DATA_ROOT when set, else the repo dir (today's
    layout). Read per call — see the module docstring."""
    v = (os.environ.get("SSC_DATA_ROOT") or "").strip()
    return Path(v) if v else SCRIPT_DIR


def is_rooted() -> bool:
    return bool((os.environ.get("SSC_DATA_ROOT") or "").strip())


def under_root(*parts) -> Path:
    """<data root>/<parts...> — the one way any data path is BUILT."""
    return data_root().joinpath(*parts)


def sqlite_db_path() -> Path:
    """The default SQLite file. SSC_DB_URL (when set) still wins upstream in
    db_layer — this is only the unset-URL default, completing the abstraction."""
    return under_root("superstars.db")


def server_log_path() -> Path:
    return under_root("server.log")


def resolve_data_path(stored) -> Path:
    """A path READ from the database (or any stored reference) -> the real file.

    relative                  -> under the active root (portable rows, #287+)
    absolute, still exists    -> as-is (pre-#287 Windows rows on the workstation)
    absolute, missing         -> re-anchored under the active root at its data
                                 anchor (the same row after the tree moved)
    absolute, no anchor       -> as-is (not a data path; caller's containment
                                 checks decide, exactly as they always have)
    """
    p = Path(str(stored))
    if not p.is_absolute():
        return under_root(*p.parts)
    if p.exists():
        return p
    parts = p.parts
    for anchor in DATA_ANCHORS:
        if anchor in parts:
            idx = parts.index(anchor)
            return under_root(*parts[idx:])
    return p


def store_rel(p) -> str:
    """The canonical STORED form for a data file: its path relative to the active
    root, POSIX separators. Falls back to the absolute string only for a path
    outside every anchor (which should not be a data file in the first place)."""
    p = Path(str(p))
    try:
        return p.resolve().relative_to(data_root().resolve()).as_posix()
    except ValueError:
        parts = p.parts
        for anchor in DATA_ANCHORS:
            if anchor in parts:
                return Path(*parts[parts.index(anchor):]).as_posix()
        return str(p)
