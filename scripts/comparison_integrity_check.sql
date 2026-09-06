-- ============================================================
-- Engine Comparison Logger — Integrity Check Suite
-- Run after the FIRST scan following Sep 7 to verify that the
-- instrumentation layer is recording correctly before analysis begins.
--
-- Expected pass conditions are listed above each query.
-- A "PASS" = the query returns zero rows (or the expected counts).
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- CHECK 1 — Coverage: signal count per engine per date
-- Purpose: confirm all four engines are logging.
-- Expected: at least one row per active engine on each scan day.
-- ────────────────────────────────────────────────────────────
SELECT
    engine,
    signal_date,
    COUNT(*)           AS signals,
    COUNT(reference_price) AS with_ref,
    COUNT(opportunity_id)  AS linked_to_opp
FROM engine_comparison_logs
GROUP BY engine, signal_date
ORDER BY signal_date DESC, engine;


-- ────────────────────────────────────────────────────────────
-- CHECK 2 — Duplicate guard
-- Expected: ZERO rows (UniqueConstraint enforces this).
-- Any row here = double-trigger or bug in deduplication.
-- ────────────────────────────────────────────────────────────
SELECT
    signal_date,
    symbol,
    engine,
    COUNT(*) AS n
FROM engine_comparison_logs
GROUP BY signal_date, symbol, engine
HAVING COUNT(*) > 1
ORDER BY signal_date, engine;


-- ────────────────────────────────────────────────────────────
-- CHECK 3 — reference_price completeness
-- Expected: missing_reference = 0 for ALL engines.
-- ────────────────────────────────────────────────────────────
SELECT
    engine,
    COUNT(*)                                  AS total,
    COUNT(reference_price)                    AS with_reference,
    COUNT(*) - COUNT(reference_price)         AS missing_reference,
    COUNT(entry_price)                        AS with_entry,
    SUM(CASE
            WHEN engine = 'SRA'
             AND ABS(reference_price - entry_price) < 0.001
            THEN 1 ELSE 0
        END)                                  AS sra_ref_equals_entry_WRONG
FROM engine_comparison_logs
GROUP BY engine
ORDER BY engine;
-- sra_ref_equals_entry_WRONG should be 0.
-- For STAGE/TREND/VOL_RADAR the opposite: ref SHOULD equal entry.


-- ────────────────────────────────────────────────────────────
-- CHECK 4 — eval_status distribution
-- Purpose: overview of how many rows are in each state.
-- Expected: no unexpected statuses beyond TP|SL|EXPIRED|OPEN|NULL.
-- ────────────────────────────────────────────────────────────
SELECT
    eval_status,
    COUNT(*)  AS n,
    engine
FROM engine_comparison_logs
GROUP BY eval_status, engine
ORDER BY eval_status, engine;


-- ────────────────────────────────────────────────────────────
-- CHECK 5 — EXPIRED completeness
-- Expected: ZERO rows.
-- An EXPIRED row must have all three: close, pnl, exit_date.
-- ────────────────────────────────────────────────────────────
SELECT
    id, signal_date, symbol, engine,
    expiry_close, expiry_pnl_pct, eval_exit_date
FROM engine_comparison_logs
WHERE eval_status = 'EXPIRED'
  AND (
      expiry_close   IS NULL
   OR expiry_pnl_pct IS NULL
   OR eval_exit_date IS NULL
   OR eval_exit_price IS NULL
  );


-- ────────────────────────────────────────────────────────────
-- CHECK 6a — OPEN consistency (must NOT have an exit date)
-- Expected: ZERO rows.
-- ────────────────────────────────────────────────────────────
SELECT id, signal_date, symbol, engine, eval_status, eval_exit_date
FROM engine_comparison_logs
WHERE eval_status = 'OPEN'
  AND eval_exit_date IS NOT NULL;

-- CHECK 6b — TP/SL/EXPIRED consistency (MUST have exit date + exit price)
-- Expected: ZERO rows.
SELECT id, signal_date, symbol, engine, eval_status, eval_exit_date, eval_exit_price
FROM engine_comparison_logs
WHERE eval_status IN ('TP', 'SL', 'EXPIRED')
  AND (eval_exit_date IS NULL OR eval_exit_price IS NULL);


-- ────────────────────────────────────────────────────────────
-- CHECK 7 — eval_pnl_pct derivation sanity
-- eval_pnl_pct must equal (eval_exit_price / reference_price - 1) * 100
-- within floating-point tolerance (0.01%).
-- Expected: ZERO rows (no discrepancy > 0.01%).
-- ────────────────────────────────────────────────────────────
SELECT
    id, signal_date, symbol, engine, eval_status,
    reference_price, eval_exit_price, eval_pnl_pct,
    ROUND((eval_exit_price / reference_price - 1) * 100, 2) AS computed_pnl,
    ABS(eval_pnl_pct - ROUND((eval_exit_price / reference_price - 1) * 100, 2)) AS delta
FROM engine_comparison_logs
WHERE eval_status IN ('TP', 'SL', 'EXPIRED')
  AND eval_exit_price IS NOT NULL
  AND reference_price IS NOT NULL
  AND ABS(
        eval_pnl_pct
        - ROUND((eval_exit_price / reference_price - 1) * 100, 2)
      ) > 0.01;


-- ────────────────────────────────────────────────────────────
-- CHECK 8 — TP threshold sanity
-- For TP rows: eval_exit_price should be ≈ reference_price × 1.07.
-- For SL rows: eval_exit_price should be ≈ reference_price × 0.95.
-- Expected: ZERO rows with delta > 0.01.
-- ────────────────────────────────────────────────────────────
SELECT
    id, signal_date, symbol, engine, eval_status,
    reference_price, eval_exit_price,
    ROUND(reference_price * 1.07, 4) AS expected_tp_price,
    ROUND(reference_price * 0.95, 4) AS expected_sl_price,
    ABS(eval_exit_price - ROUND(
        CASE eval_status
            WHEN 'TP' THEN reference_price * 1.07
            WHEN 'SL' THEN reference_price * 0.95
        END, 4)) AS price_delta
FROM engine_comparison_logs
WHERE eval_status IN ('TP', 'SL')
  AND eval_exit_price IS NOT NULL
  AND ABS(eval_exit_price - CASE eval_status
        WHEN 'TP' THEN reference_price * 1.07
        WHEN 'SL' THEN reference_price * 0.95
      END) > 0.01;


-- ────────────────────────────────────────────────────────────
-- CHECK 9 — No stale rows: OPEN past the hold window
-- A row with eval_status = OPEN and signal_date older than
-- COMMON_MAX_HOLD * 2 calendar days is suspicious — the update
-- job should have resolved it to EXPIRED by now.
-- Expected: ZERO rows.
-- ────────────────────────────────────────────────────────────
SELECT
    id, signal_date, symbol, engine, eval_status,
    CURRENT_DATE - signal_date AS age_days
FROM engine_comparison_logs
WHERE eval_status = 'OPEN'
  AND signal_date < CURRENT_DATE - 20;


-- ────────────────────────────────────────────────────────────
-- CHECK 10 — Pipeline funnel: native signals → logged → evaluated
-- This is the "no silent failures" check.
-- Joins opportunities (native engine output) with comparison_logs.
-- Expected: missing = 0 on every scan day.
-- Non-zero missing means a signal fired but the logger dropped it.
-- ────────────────────────────────────────────────────────────
SELECT
    o.run_date                               AS scan_date,
    CASE
        WHEN o.opp_type LIKE 'STAGE_%'  THEN 'STAGE'
        WHEN o.opp_type LIKE 'TREND_%'  THEN 'TREND'
        WHEN o.opp_type LIKE 'SRA_%'    THEN 'SRA'
        WHEN o.opp_type = 'VOL_RADAR'   THEN 'VOL_RADAR'
        ELSE 'OTHER'
    END                                      AS engine,
    COUNT(o.id)                              AS native_signals,
    COUNT(c.id)                              AS logged_signals,
    COUNT(o.id) - COUNT(c.id)               AS missing,
    COUNT(CASE WHEN c.eval_status IN ('TP','SL','EXPIRED') THEN 1 END)
                                             AS evaluated
FROM opportunities o
LEFT JOIN engine_comparison_logs c
    ON c.opportunity_id = o.id
WHERE o.run_date >= CURRENT_DATE - 21
  AND o.opp_type NOT LIKE 'MOMENTUM%'
  AND o.strategy_version_id IS NOT NULL
GROUP BY o.run_date, engine
ORDER BY o.run_date DESC, engine;


-- ────────────────────────────────────────────────────────────
-- SUMMARY VIEW — run this last as the overall pass/fail readout
-- ────────────────────────────────────────────────────────────
SELECT 'CHECK_2_duplicates'       AS check_name,
       COUNT(*)                   AS failing_rows
FROM (
    SELECT signal_date, symbol, engine
    FROM engine_comparison_logs
    GROUP BY signal_date, symbol, engine
    HAVING COUNT(*) > 1
) _dup

UNION ALL

SELECT 'CHECK_3_missing_reference',
       SUM(CASE WHEN reference_price IS NULL THEN 1 ELSE 0 END)
FROM engine_comparison_logs

UNION ALL

SELECT 'CHECK_5_expired_incomplete',
       COUNT(*)
FROM engine_comparison_logs
WHERE eval_status = 'EXPIRED'
  AND (expiry_close IS NULL OR expiry_pnl_pct IS NULL
       OR eval_exit_date IS NULL OR eval_exit_price IS NULL)

UNION ALL

SELECT 'CHECK_6a_open_has_exit_date',
       COUNT(*)
FROM engine_comparison_logs
WHERE eval_status = 'OPEN' AND eval_exit_date IS NOT NULL

UNION ALL

SELECT 'CHECK_6b_closed_missing_exit',
       COUNT(*)
FROM engine_comparison_logs
WHERE eval_status IN ('TP','SL','EXPIRED')
  AND (eval_exit_date IS NULL OR eval_exit_price IS NULL)

UNION ALL

SELECT 'CHECK_7_pnl_derivation_error',
       COUNT(*)
FROM engine_comparison_logs
WHERE eval_status IN ('TP','SL','EXPIRED')
  AND eval_exit_price IS NOT NULL
  AND reference_price IS NOT NULL
  AND ABS(eval_pnl_pct
          - ROUND((eval_exit_price / reference_price - 1) * 100, 2)) > 0.01

UNION ALL

SELECT 'CHECK_9_stale_open_rows',
       COUNT(*)
FROM engine_comparison_logs
WHERE eval_status = 'OPEN'
  AND signal_date < CURRENT_DATE - 20

UNION ALL

-- CHECK 10 in SUMMARY: subquery required because SUM(COUNT(...)) is
-- a nested aggregate which is invalid SQL in all dialects.
SELECT 'CHECK_10_pipeline_missing' AS check_name,
       COALESCE((
           SELECT SUM(missing)
           FROM (
               SELECT COUNT(o.id) - COUNT(c.id) AS missing
               FROM opportunities o
               LEFT JOIN engine_comparison_logs c
                   ON c.opportunity_id = o.id
               WHERE o.run_date >= CURRENT_DATE - 21
                 AND o.opp_type NOT LIKE 'MOMENTUM%'
                 AND o.strategy_version_id IS NOT NULL
               GROUP BY o.run_date,
                   CASE
                       WHEN o.opp_type LIKE 'STAGE_%' THEN 'STAGE'
                       WHEN o.opp_type LIKE 'TREND_%' THEN 'TREND'
                       WHEN o.opp_type LIKE 'SRA_%'   THEN 'SRA'
                       WHEN o.opp_type = 'VOL_RADAR'  THEN 'VOL_RADAR'
                       ELSE 'OTHER'
                   END
               HAVING COUNT(o.id) > COUNT(c.id)
           ) _missing
       ), 0)

ORDER BY check_name;
-- ALL failing_rows should be 0 for a complete PASS.
