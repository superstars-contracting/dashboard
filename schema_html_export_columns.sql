-- =====================================================================
-- Add html_export_path to both credential tables.
--
-- Per CLAUDE.md HTML-first rule, the canonical rendered output of an
-- issued credential is HTML (browser print-to-PDF on demand) rather
-- than WeasyPrint-generated PDF. WeasyPrint requires GTK runtime libs
-- that aren't installed on this Windows workstation — surfaced as the
-- libgobject-2.0-0 import error during E2-B smoke testing.
--
-- pdf_export_path stays on both tables for future re-introduction
-- (e.g., if GTK runtime gets installed or a different PDF renderer
-- like Playwright headless Chromium is added). For now it stays NULL.
-- =====================================================================

ALTER TABLE cof_cards ADD COLUMN html_export_path TEXT;
ALTER TABLE company_id_cards ADD COLUMN html_export_path TEXT;
