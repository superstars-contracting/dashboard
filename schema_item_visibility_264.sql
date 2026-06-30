-- =====================================================================
-- #264 — the per-item VISIBILITY ENGINE (North Star §6, default-deny).
--
-- The spine of external sharing: client now, design_team + vendor later. Every
-- shareable item (photo v1; document next) is INTERNAL-ONLY by default — it reaches
-- an external audience ONLY if an explicit row says so. No row = not shared. This is
-- default-deny BY CONSTRUCTION, not by a filter that could be forgotten.
--
--   item_visibility  — presence of (item_type, item_id, audience) = shared to that
--                      audience. UNIQUE so a share is idempotent.
--   item_redflag     — a STICKY "take offline" lever: while a row exists the item is
--                      suppressed from ALL external audiences AND new shares are
--                      blocked (the legal/sensitivity panic button). Reversible (unflag).
--   visibility_audit — who shared / unshared / red-flagged / unflagged what, when.
--
-- audience: 'client' (v1). 'design' / 'vendor:<id>' plug in later with no schema change.
-- item_type: 'photo' (v1, -> field_photos.id). 'document' later, identically.
-- Dates are LOCAL ISO strings written by the app (CLAUDE.md). NO FK constraints (keeps
-- the engine item-type-agnostic + dual-backend simple; integrity enforced in code).
--
-- Canonical SQLite DDL (reference). apply_item_visibility_264.py emits the backend-correct
-- PRIMARY KEY (Postgres IDENTITY) at apply time.
-- =====================================================================

CREATE TABLE IF NOT EXISTS item_visibility (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  item_type   TEXT    NOT NULL,
  item_id     INTEGER NOT NULL,
  audience    TEXT    NOT NULL,
  shared_by   INTEGER,
  shared_at   TEXT,
  UNIQUE (item_type, item_id, audience)
);
CREATE INDEX IF NOT EXISTS idx_itemvis_lookup   ON item_visibility(item_type, item_id);
CREATE INDEX IF NOT EXISTS idx_itemvis_audience ON item_visibility(audience, item_type);

CREATE TABLE IF NOT EXISTS item_redflag (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  item_type   TEXT    NOT NULL,
  item_id     INTEGER NOT NULL,
  flagged_by  INTEGER,
  flagged_at  TEXT,
  UNIQUE (item_type, item_id)
);

CREATE TABLE IF NOT EXISTS visibility_audit (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  item_type   TEXT    NOT NULL,
  item_id     INTEGER NOT NULL,
  audience    TEXT,
  action      TEXT    NOT NULL,   -- share | unshare | redflag | unflag
  actor_id    INTEGER,
  at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_visaudit_item ON visibility_audit(item_type, item_id);
