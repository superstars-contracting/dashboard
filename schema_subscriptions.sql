-- =====================================================================
-- Subscriptions & assets tracking.
-- One row per recurring service or one-time asset that the company pays for.
-- Started 2026-05-15 as part of the "hard workers to hard thinkers" shift.
-- Goal: never have to back-fill subscription data again. Every new signup
-- adds a row; every renewal updates one. This becomes the source of truth
-- for what the org pays for and when.
-- =====================================================================

CREATE TABLE IF NOT EXISTS subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_name TEXT NOT NULL,                   -- "Google Workspace Business Standard"
  provider TEXT NOT NULL,                       -- "Google", "1Password", "Lenovo"
  category TEXT NOT NULL,                       -- Productivity, Security, Connectivity, Hardware, AI, Communications, Cloud, Development, Industry, Other
  owner_email TEXT NOT NULL DEFAULT 'admin@superstarscontracting.com',
  billing_email TEXT NOT NULL DEFAULT 'subscriptions@superstarscontracting.com',
  plan_tier TEXT,                               -- "Business Standard", "Premium", custom config
  seats INTEGER DEFAULT 1,                      -- How many seats / units
  unit_cost_usd REAL,                           -- Cost per seat per billing cycle
  billing_cycle TEXT NOT NULL,                  -- monthly, annual, quarterly, one_time, custom
  start_date TEXT,                              -- YYYY-MM-DD
  renewal_date TEXT,                            -- YYYY-MM-DD or NULL for one_time
  status TEXT NOT NULL DEFAULT 'active',        -- active, trial, paused, canceled, pending_auth
  mfa_method TEXT,                              -- yubikey, totp, sms, none, n/a
  admin_url TEXT,                               -- URL to the admin portal
  account_id TEXT,                              -- Vendor-side customer ID (when known)
  payment_method TEXT,                          -- "Card ending 4242", "ACH", etc.
  notes TEXT,                                   -- Free text
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_subs_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_subs_category ON subscriptions(category);
CREATE INDEX IF NOT EXISTS idx_subs_renewal ON subscriptions(renewal_date);
CREATE INDEX IF NOT EXISTS idx_subs_provider ON subscriptions(provider);

-- Computed view: total monthly burn (annual subs divided by 12, monthly subs as-is, one-time excluded)
CREATE VIEW IF NOT EXISTS subscriptions_monthly_burn AS
SELECT
  category,
  COUNT(*) AS active_count,
  ROUND(SUM(
    CASE
      WHEN billing_cycle = 'monthly' THEN unit_cost_usd * seats
      WHEN billing_cycle = 'annual' THEN (unit_cost_usd * seats) / 12.0
      WHEN billing_cycle = 'quarterly' THEN (unit_cost_usd * seats) / 3.0
      ELSE 0
    END
  ), 2) AS monthly_usd
FROM subscriptions
WHERE status = 'active'
GROUP BY category
ORDER BY monthly_usd DESC;

-- Computed view: renewals coming up in the next 30 days
CREATE VIEW IF NOT EXISTS subscriptions_upcoming_renewals AS
SELECT
  service_name, provider, plan_tier, seats, unit_cost_usd,
  billing_cycle, renewal_date,
  CAST((julianday(renewal_date) - julianday('now')) AS INTEGER) AS days_until_renewal
FROM subscriptions
WHERE status = 'active'
  AND renewal_date IS NOT NULL
  AND renewal_date != 'PENDING'
  AND julianday(renewal_date) - julianday('now') BETWEEN 0 AND 30
ORDER BY renewal_date;
