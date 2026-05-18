-- =====================================================================
-- CoF eligibility flag correction (user clarification 2026-05-18).
--
-- The D0-era seed flagged SCAFFOLD-16 + SCAFFOLD-32 as CoF prerequisites.
-- SCAFFOLD-32 is a phantom cert (per task #35) — no worker actually
-- holds it. The real second prerequisite is RIGGER-32 (32-hr Rigging
-- Foreman), which was sitting unflagged in cert_types.
--
-- Final state after this migration:
--   SCAFFOLD-16  is_cof_prerequisite=1  (unchanged)
--   SCAFFOLD-32  is_cof_prerequisite=0  (was 1 — was wrong, fixed)
--   RIGGER-32    is_cof_prerequisite=1  (was 0 — should have been flagged)
--
-- UPDATE is naturally idempotent — re-running sets the same values,
-- no schema mutation, no duplicate-column errors expected.
-- =====================================================================

UPDATE cert_types SET is_cof_prerequisite=0 WHERE cert_type_id='SCAFFOLD-32';
UPDATE cert_types SET is_cof_prerequisite=1 WHERE cert_type_id='RIGGER-32';
