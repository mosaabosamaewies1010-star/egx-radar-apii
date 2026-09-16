-- ─────────────────────────────────────────────────────────────────────────────
-- ThndrX OHLCV tables — Phase 1 migration
-- Run once in Render PostgreSQL (via Supabase SQL Editor or psql)
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. Daily OHLCV candles from ThndrX (primary key = symbol + day → UPSERT-safe)
CREATE TABLE IF NOT EXISTS thndrx_ohlcv (
    symbol   VARCHAR(30)    NOT NULL,
    day      DATE           NOT NULL,
    open     NUMERIC(14, 4) NOT NULL,
    high     NUMERIC(14, 4) NOT NULL,
    low      NUMERIC(14, 4) NOT NULL,
    close    NUMERIC(14, 4) NOT NULL,
    volume   BIGINT         NOT NULL,
    value    NUMERIC(22, 4),
    industry VARCHAR(120),
    PRIMARY KEY (symbol, day)
);

CREATE INDEX IF NOT EXISTS idx_thndrx_ohlcv_day
    ON thndrx_ohlcv (day);

-- 2. Upload freshness log — one row per session date
--    Radar reads latest row to determine data source and staleness.
CREATE TABLE IF NOT EXISTS thndrx_freshness (
    id               SERIAL       PRIMARY KEY,
    session_date     DATE         NOT NULL,
    symbol_count     INTEGER      NOT NULL,
    row_count        INTEGER      NOT NULL,
    uploaded_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    uploader_version VARCHAR(10)  NOT NULL DEFAULT '1.0',
    notes            TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_thndrx_freshness_session
    ON thndrx_freshness (session_date);

-- 3. Verify
SELECT
    (SELECT COUNT(*) FROM thndrx_ohlcv)    AS ohlcv_rows,
    (SELECT COUNT(*) FROM thndrx_freshness) AS freshness_rows;
