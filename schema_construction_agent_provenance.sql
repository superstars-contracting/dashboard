-- =====================================================================
-- Construction Specialist Agent — provenance audit table (#198)
-- =====================================================================
-- construction_agent_provenance — one row per substantive Construction
--   Specialist Agent interaction, written by the PII-safe provenance
--   helper (agents/construction_specialist/provenance.py) on the
--   Task-tool sub-agent path. Operator decision Q3 (spec §10): a DB
--   table from day one, not a log file — "no agent decision is
--   unauditable."
--
-- PII discipline (CLAUDE.md PII rule): this table NEVER stores worker
--   names, PIN values, or rate/pay values. Workers are referenced as
--   W-#### only. The helper applies a defensive scrub on top of the
--   agent's W-#### discipline.
--
-- Dates: asked_at and created_at are written as LOCAL datetime strings
--   by the helper (per CLAUDE.md dates rule — never UTC). The
--   CURRENT_TIMESTAMP default below is a fallback only; the helper
--   always supplies a local value so the UTC default never fires in
--   normal operation.
--
-- interaction_id is the stable human-readable handle for one Q&A.
--   Production rows: "CAP-YYYYMMDD-HHMMSS-xxxx". Test rows MUST carry a
--   synthetic prefix ("SMK-...") so the anti-corruption meta-smoke
--   (tests/smoke_no_production_data_corruption.py) treats them as
--   expected smoke residue, not production-data pollution.
--
-- Re-run safe: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
-- via the split_statements pattern used by the rest of the migrations.
-- =====================================================================

CREATE TABLE IF NOT EXISTS construction_agent_provenance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  interaction_id TEXT NOT NULL UNIQUE,
  asked_at TEXT NOT NULL,
  question_text TEXT NOT NULL,
  corpus_version TEXT,
  sources_cited TEXT,
  answer_summary TEXT,
  operator_disposition TEXT DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cap_asked_at    ON construction_agent_provenance(asked_at);
CREATE INDEX IF NOT EXISTS idx_cap_interaction ON construction_agent_provenance(interaction_id);
CREATE INDEX IF NOT EXISTS idx_cap_disposition ON construction_agent_provenance(operator_disposition);
