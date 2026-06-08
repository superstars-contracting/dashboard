-- #235 Field Photos — Phase 1. Per-project work-in-progress photo gallery +
-- Unassigned sort/assign tray + bulk upload.
--
-- PII / path discipline (per CLAUDE.md): file_path + thumb_path live on-disk
-- ONLY and are NEVER serialized to JSON — the gated routes
-- GET /api/photos/<id>/thumb and /file serve the bytes. Files are stored under
-- data_room/field_photos/<project>/<uuid>/(full|thumb).<ext>. GPS / camera EXIF
-- is STRIPPED from the stored images (privacy); only taken_at is kept (LOCAL).
-- Dates are LOCAL (never UTC).
--
-- taken_at = EXIF DateTimeOriginal (LOCAL). If a photo has no EXIF date we fall
-- back to file mtime / upload time and set taken_at_estimated=1 so time-grouping
-- still works and the UI can flag it. orientation_applied=1 means the EXIF
-- Orientation was baked into the pixels (photo stored upright).

CREATE TABLE IF NOT EXISTS field_photos (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code        TEXT NOT NULL,                -- FK projects.project_code
  drop_id             TEXT,                         -- FK drops.drop_id; NULL = Unassigned
  worker_id           TEXT,                         -- nullable (W-####)
  stage               TEXT,                         -- nullable (Survey/Patch/Routing/...)
  caption             TEXT,                         -- nullable
  taken_at            TEXT,                         -- LOCAL ISO 'YYYY-MM-DD HH:MM:SS'; nullable
  taken_at_estimated  INTEGER NOT NULL DEFAULT 0,   -- 1 = fell back to mtime/upload (no EXIF date)
  uploaded_at         TEXT NOT NULL,                -- LOCAL ISO timestamp
  uploaded_by_uid     INTEGER,                      -- users.id (PII-safe token; no names)
  file_path           TEXT NOT NULL,                -- on-disk display image — NEVER in JSON
  thumb_path          TEXT NOT NULL,                -- on-disk thumbnail — NEVER in JSON
  file_name           TEXT,                         -- original filename (display)
  file_size           INTEGER,                      -- stored display-image size (bytes)
  mime                TEXT,                          -- stored mime (image/jpeg etc.)
  width               INTEGER,                      -- stored display-image width (px, upright)
  height              INTEGER,                      -- stored display-image height (px, upright)
  orientation_applied INTEGER NOT NULL DEFAULT 0    -- 1 = EXIF orientation baked into pixels
);
CREATE INDEX IF NOT EXISTS idx_fieldphotos_project    ON field_photos(project_code, drop_id);
CREATE INDEX IF NOT EXISTS idx_fieldphotos_taken      ON field_photos(project_code, taken_at);
CREATE INDEX IF NOT EXISTS idx_fieldphotos_unassigned ON field_photos(project_code, drop_id, taken_at);
