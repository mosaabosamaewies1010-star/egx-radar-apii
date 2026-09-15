-- ─────────────────────────────────────────────────────────────────────────────
-- Enable Row Level Security on all EGX Radar tables
-- Run once in Supabase SQL Editor (Dashboard → SQL Editor → New query)
--
-- Strategy:
--   The app uses a DIRECT PostgreSQL connection (DATABASE_URL via SQLAlchemy).
--   It NEVER calls the Supabase REST API — no anon key is used anywhere.
--   Enabling RLS with NO policies blocks the anon role (what we want),
--   while service_role bypasses RLS automatically (app keeps working).
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. Enable RLS on every table
ALTER TABLE analytics_events       ENABLE ROW LEVEL SECURITY;
ALTER TABLE engine_comparison_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications          ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunities          ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments               ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_holdings     ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_regime_history  ENABLE ROW LEVEL SECURITY;
ALTER TABLE scan_logs              ENABLE ROW LEVEL SECURITY;
ALTER TABLE radar_score_history    ENABLE ROW LEVEL SECURITY;
ALTER TABLE stocks                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE strategy_versions      ENABLE ROW LEVEL SECURITY;
ALTER TABLE users                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlists             ENABLE ROW LEVEL SECURITY;

-- 2. Verify (should show rls_enabled = true for all 13 tables)
SELECT tablename, rowsecurity AS rls_enabled
FROM   pg_tables
WHERE  schemaname = 'public'
ORDER  BY tablename;

-- ─────────────────────────────────────────────────────────────────────────────
-- After running: Supabase security warning disappears.
-- App behavior: UNCHANGED (service_role bypasses RLS by design).
-- anon key access: BLOCKED on all tables (nobody uses it — intended).
-- ─────────────────────────────────────────────────────────────────────────────
