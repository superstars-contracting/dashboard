-- Expense / Spend module — Batch A foundation (#218).
-- Per-project expense capture + line items + (reserved) Batch-B alias memory.
-- Money: stored as REAL but ALL arithmetic is done in Python with Decimal and
-- quantized to 2dp, and aggregates are Decimal-summed — so there is no float
-- drift in totals/KPIs/rollups. Dates are LOCAL YYYY-MM-DD (never UTC).
-- receipt_image_path is server-only and is NEVER serialized into any JSON.

CREATE TABLE IF NOT EXISTS expenses (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code       TEXT NOT NULL,
  vendor             TEXT,
  doc_type           TEXT,
  doc_number         TEXT,
  order_number       TEXT,
  expense_date       TEXT,                 -- LOCAL YYYY-MM-DD
  category           TEXT,
  cost_code          TEXT,                 -- nullable; job-cost bucket (free field)
  payment_method     TEXT,                 -- nullable
  total              REAL NOT NULL DEFAULT 0,   -- sum of line extended_price where out_of_cost=0
  status             TEXT NOT NULL DEFAULT 'needs_review',  -- draft | needs_review | reviewed
  receipt_image_path TEXT,                 -- server-only; NEVER in JSON
  notes              TEXT,
  created_at         TEXT,
  created_by_uid     INTEGER,
  reviewed_by_uid    INTEGER,
  reviewed_at        TEXT,
  synced_to_qb       INTEGER NOT NULL DEFAULT 0,  -- reserved for QuickBooks
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE TABLE IF NOT EXISTS expense_line_items (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  expense_id         INTEGER NOT NULL,
  item_id            TEXT,                 -- vendor SKU / item code (nullable)
  description        TEXT,
  product_class      TEXT NOT NULL DEFAULT 'OTHER',  -- enum from EXPENSE_PRODUCT_TAXONOMY
  normalized_product TEXT,                 -- groupable product name (nullable; Batch B fills)
  qty                REAL NOT NULL DEFAULT 0,
  unit               TEXT,                 -- enum from taxonomy unit list
  unit_price         REAL NOT NULL DEFAULT 0,
  extended_price     REAL NOT NULL DEFAULT 0,
  is_refundable      INTEGER NOT NULL DEFAULT 0,
  out_of_cost        INTEGER NOT NULL DEFAULT 0,
  sort_order         INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE CASCADE
);

-- Reserved for Batch-B classifier learning. Created empty now so B has a home;
-- no read/write logic in Batch A.
CREATE TABLE IF NOT EXISTS expense_class_alias (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor             TEXT,
  item_key           TEXT,                 -- item_id OR normalized description
  product_class      TEXT,
  normalized_product TEXT,
  updated_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_expenses_project   ON expenses(project_code);
CREATE INDEX IF NOT EXISTS idx_expenses_status    ON expenses(status);
CREATE INDEX IF NOT EXISTS idx_expenses_date      ON expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_expli_expense      ON expense_line_items(expense_id);
CREATE INDEX IF NOT EXISTS idx_expli_class        ON expense_line_items(product_class);
CREATE INDEX IF NOT EXISTS idx_expalias_lookup    ON expense_class_alias(vendor, item_key);

-- #219 Batch B — multi-page AI scans store every page; receipt_image_path points
-- at page 1 and receipt_page_count records how many pages live in its folder.
-- ALTER is idempotent here: the migration runner skips "duplicate column".
ALTER TABLE expenses ADD COLUMN receipt_page_count INTEGER;
