-- #209 — Per-user dashboard widget layouts (GENERIC, reusable across pages).
--
-- One row per (user_id, page_key). `layout_json` holds ONLY widget ids + grid
-- positions ({id,x,y,w,h}) — never names, rates, PINs, or any business data
-- (PII-safe by construction; the save endpoint sanitizes to that shape).
-- page_key lets the same table + JS serve Project Health AND the company
-- console (and any future surface) without schema changes.
CREATE TABLE IF NOT EXISTS dashboard_layouts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    page_key    TEXT    NOT NULL,
    layout_json TEXT    NOT NULL,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, page_key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_dashboard_layouts_user_page
    ON dashboard_layouts(user_id, page_key);
