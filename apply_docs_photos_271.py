#!/usr/bin/env python3
"""#271 — document version linkage + field-photo EXIF backfill.

Two additive, idempotent, dual-backend steps (SQLite default / Postgres via SSC_DB_URL):

  1. SCHEMA: project_documents.supersedes_id INTEGER (nullable) + index — the version
     chain. `Update` inserts a NEW row whose supersedes_id points at the row it
     replaced; that old row gets superseded=1 and is NEVER deleted. History = walking
     the chain. No CHECK/FK by design (matches the #264/#269 engine tables; integrity
     enforced in code, teardown-simple on both backends).

  2. BACKFILL: for field_photos rows still carrying the upload-time fallback
     (taken_at_estimated=1) or a NULL taken_at, re-read EXIF DateTimeOriginal from the
     on-disk stored image and fill the true capture time where one exists. HONESTY
     NOTE: the #235 pipeline deliberately re-saves stored images WITHOUT EXIF (GPS/
     privacy strip), so photos processed by that pipeline have no on-disk EXIF to
     recover — those rows are left exactly as they are (correctly counted as
     'no readable EXIF'). The pass exists for any row whose stored file DOES carry
     EXIF (imports, pre-pipeline files, future original-preserving paths). Row counts
     are never changed; re-running is safe (a filled row flips taken_at_estimated=0
     and leaves the eligible set).

PII: file paths are NEVER printed/logged — counts and booleans only.
Run:  python apply_docs_photos_271.py           (SSC_DB_URL unset -> live)
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402


def _column_exists(conn, table: str, col: str) -> bool:
    if db_layer.is_postgres():
        return bool(conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=? AND column_name=?",
            (table, col)).fetchone())
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})").fetchall())


def ensure_doc_versions_schema(conn) -> dict:
    """Add project_documents.supersedes_id + its index if missing. Idempotent."""
    added = not _column_exists(conn, "project_documents", "supersedes_id")
    if added:
        conn.execute("ALTER TABLE project_documents ADD COLUMN supersedes_id INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projdoc_supersedes "
                 "ON project_documents(supersedes_id)")
    return {"project_documents.supersedes_id": added}


def backfill_photo_exif(conn) -> dict:
    """Fill taken_at from on-disk EXIF for fallback-flagged rows. Idempotent; counts
    unchanged; paths never printed. Returns {eligible, filled, no_exif, missing_file}."""
    import field_photos as fp  # reuses the exact EXIF reader the upload path uses
    from PIL import Image
    import io

    rows = conn.execute(
        "SELECT id, file_path FROM field_photos "
        "WHERE taken_at_estimated=1 OR taken_at IS NULL ORDER BY id").fetchall()
    filled = no_exif = missing = 0
    for r in rows:
        p = Path(r[1] or "")
        if not r[1] or not p.exists():
            missing += 1
            continue
        try:
            im = Image.open(io.BytesIO(p.read_bytes()))
            im.load()
            ts = fp._exif_taken_at(im)
        except Exception:
            ts = None
        if ts:
            conn.execute(
                "UPDATE field_photos SET taken_at=?, taken_at_estimated=0 WHERE id=?",
                (ts, r[0]))
            filled += 1
        else:
            no_exif += 1
    return {"eligible": len(rows), "filled": filled,
            "no_exif": no_exif, "missing_file": missing}


def main() -> int:
    backend = "postgres" if db_layer.is_postgres() else "sqlite"
    print(f"#271 doc versions + photo EXIF backfill — backend={backend}")
    conn = db_layer.connect(pragma_fk=True)
    try:
        pre_docs = conn.execute("SELECT COUNT(*) FROM project_documents").fetchone()[0]
        pre_photos = conn.execute("SELECT COUNT(*) FROM field_photos").fetchone()[0]
        changed = ensure_doc_versions_schema(conn)
        for k, added in changed.items():
            print(f"  {k}: {'added' if added else 'already present (skipped)'}")
        stats = backfill_photo_exif(conn)
        conn.commit()
        print(f"  exif backfill: eligible={stats['eligible']} filled={stats['filled']} "
              f"no_exif={stats['no_exif']} missing_file={stats['missing_file']}")
        post_docs = conn.execute("SELECT COUNT(*) FROM project_documents").fetchone()[0]
        post_photos = conn.execute("SELECT COUNT(*) FROM field_photos").fetchone()[0]
        assert (pre_docs, pre_photos) == (post_docs, post_photos), "row counts changed!"
        print(f"  row counts unchanged: project_documents={post_docs} field_photos={post_photos}")
    finally:
        conn.close()
    print("done — idempotent; safe to re-run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
