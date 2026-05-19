-- =====================================================================
-- Add revision support to cof_cards.
--
-- cof_issuer originally used card_id = SSC-COF-{employee_id} as the PK,
-- so re-issuing for the same worker collided on UNIQUE since the route
-- marks the prior row 'replaced' (same PK) before INSERT of the new
-- 'issued' row (also same PK) -> sqlite3.IntegrityError surfaced in E4
-- smoke testing.
--
-- Fix mirrors company_id_cards: card_id now SSC-COF-{employee_id}-{rev}
-- and a new card_number_display column carries the stable human-readable
-- identifier (SSC-COF-{employee_id}) that doesn't change across reissues.
--
-- Backfill: existing rows get card_number_display = card_id (which IS
-- the stable display name for any row issued before this migration).
-- =====================================================================

ALTER TABLE cof_cards ADD COLUMN card_number_display TEXT;
UPDATE cof_cards SET card_number_display = card_id WHERE card_number_display IS NULL;
