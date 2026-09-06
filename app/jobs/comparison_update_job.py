"""
Comparison Update Job — fills forward-path and eval fields in engine_comparison_logs.

Runs daily at 16:05 Cairo (5 min after outcome_job) on trading days (Sun–Thu).
Processes OPEN and NULL-status rows from the past 21 calendar days
(covers 10 trading sessions with buffer for weekends/holidays).

For each eligible row:
  1. Fetches 1-month OHLCV for the symbol.
  2. Slices to bars strictly AFTER signal_date (so day 1 = next trading session).
  3. Computes forward returns, MFE, MAE from reference_price.
  4. Applies Common Evaluation Layer (same for ALL engines):
       TP threshold = reference_price × 1.07  (intraday high crosses it → TP)
       SL threshold = reference_price × 0.95  (intraday low  crosses it → SL)
       MAX_HOLD     = 10 trading sessions
  5. Sets expiry_close + expiry_pnl_pct (close-based, from reference_price):
       TP/SL  → close of the session where the threshold was first breached
       EXPIRED → close of the 10th session
  6. eval_status stays EXPIRED for positions that survived 10 days without
     hitting TP or SL — never converts to WIN/LOSS.

Two performance lenses available after update:
  Common Target Test — eval_status (TP|SL|EXPIRED), eval_pnl_pct
  10-Day MTM Return  — fwd_10d_pct, expiry_pnl_pct
"""
import logging
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

COMMON_TP_PCT   = 7.0   # +7.0%
COMMON_SL_PCT   = 5.0   # -5.0%  (stored positive; applied as 1 - x/100)
COMMON_MAX_HOLD = 10    # trading sessions


def run_comparison_update_job(app) -> None:
    with app.app_context():
        try:
            from app import db
            from app.models.engine_comparison_log import EngineComparisonLog
            from app.utils.data_fetcher import fetch_ohlcv

            today  = date.today()
            cutoff = today - timedelta(days=21)   # fix #4: was 16, now 21

            # fix #2: include OPEN rows — they were set in a prior run while
            # still within the hold window and must be re-evaluated each day.
            pending = (
                EngineComparisonLog.query
                .filter(
                    EngineComparisonLog.signal_date >= cutoff,
                    db.or_(
                        EngineComparisonLog.eval_status.is_(None),
                        EngineComparisonLog.eval_status == "OPEN",
                    ),
                    EngineComparisonLog.reference_price.isnot(None),
                )
                .all()
            )

            if not pending:
                logger.info("comparison_update: no pending logs to update")
                return

            logger.info("comparison_update: updating %d logs", len(pending))

            from collections import defaultdict
            by_symbol: dict = defaultdict(list)
            for row in pending:
                by_symbol[row.symbol].append(row)

            updated = 0
            for symbol, rows in by_symbol.items():
                try:
                    df = fetch_ohlcv(symbol, period="1mo")
                    if df is None or df.empty:
                        continue

                    df = df.sort_index()
                    close_col = next((c for c in df.columns if c.lower() == "close"), None)
                    high_col  = next((c for c in df.columns if c.lower() == "high"),  None)
                    low_col   = next((c for c in df.columns if c.lower() == "low"),   None)
                    if not all([close_col, high_col, low_col]):
                        continue

                    for row in rows:
                        try:
                            ref = row.reference_price   # always today's close at signal time

                            # Slice to trading sessions STRICTLY after signal_date
                            signal_dt = datetime.combine(row.signal_date, datetime.min.time())
                            future    = df[df.index > signal_dt]
                            if future.empty:
                                continue  # data not yet available

                            closes = future[close_col].values
                            highs  = future[high_col].values
                            lows   = future[low_col].values
                            dates  = future.index   # DatetimeIndex of trading sessions

                            # ── Forward returns from reference_price ───────────
                            def _fwd(n):
                                if len(closes) >= n:
                                    return round((closes[n - 1] / ref - 1) * 100, 2)
                                return None

                            row.fwd_1d_pct  = _fwd(1)
                            row.fwd_3d_pct  = _fwd(3)
                            row.fwd_5d_pct  = _fwd(5)
                            row.fwd_10d_pct = _fwd(10)

                            # ── MFE / MAE over COMMON_MAX_HOLD sessions ────────
                            hold_highs = highs[:COMMON_MAX_HOLD]
                            hold_lows  = lows[:COMMON_MAX_HOLD]
                            if len(hold_highs):
                                mfe_raw = max(hold_highs)
                                mae_raw = min(hold_lows)
                                row.mfe_pct     = round((mfe_raw / ref - 1) * 100, 2)
                                row.mae_pct     = round((mae_raw / ref - 1) * 100, 2)
                                row.days_to_mfe = int(hold_highs.tolist().index(mfe_raw)) + 1

                            # ── Common Evaluation Layer ────────────────────────
                            tp_thresh = ref * (1 + COMMON_TP_PCT / 100)
                            sl_thresh = ref * (1 - COMMON_SL_PCT / 100)
                            hold      = min(COMMON_MAX_HOLD, len(closes))

                            hit_tp_day = hit_sl_day = None
                            for i in range(hold):
                                if hit_tp_day is None and highs[i] >= tp_thresh:
                                    hit_tp_day = i + 1
                                if hit_sl_day is None and lows[i] <= sl_thresh:
                                    hit_sl_day = i + 1
                                if hit_tp_day and hit_sl_day:
                                    break

                            if hit_tp_day and (hit_sl_day is None or hit_tp_day <= hit_sl_day):
                                # TP hit first (or same day — TP wins).
                                # eval_exit_price = tp_thresh (the intraday level crossed).
                                # eval_pnl_pct    = (tp_thresh / ref - 1)*100 = exactly +TP%.
                                # expiry_close    = actual close of that session (may differ).
                                _tp_thresh = round(ref * (1 + COMMON_TP_PCT / 100), 4)
                                row.eval_hit_tp     = True
                                row.eval_hit_sl     = False
                                row.eval_status     = "TP"
                                row.eval_exit_price = _tp_thresh
                                row.eval_pnl_pct    = round((_tp_thresh / ref - 1) * 100, 2)
                                row.eval_hold_days  = hit_tp_day
                                row.eval_exit_date  = dates[hit_tp_day - 1].date()
                                row.expiry_close    = round(float(closes[hit_tp_day - 1]), 4)
                                row.expiry_pnl_pct  = round(
                                    (closes[hit_tp_day - 1] / ref - 1) * 100, 2
                                )

                            elif hit_sl_day and (hit_tp_day is None or hit_sl_day < hit_tp_day):
                                # SL hit first.
                                # eval_exit_price = sl_thresh (the intraday level crossed).
                                _sl_thresh = round(ref * (1 - COMMON_SL_PCT / 100), 4)
                                row.eval_hit_tp     = False
                                row.eval_hit_sl     = True
                                row.eval_status     = "SL"
                                row.eval_exit_price = _sl_thresh
                                row.eval_pnl_pct    = round((_sl_thresh / ref - 1) * 100, 2)
                                row.eval_hold_days  = hit_sl_day
                                row.eval_exit_date  = dates[hit_sl_day - 1].date()
                                row.expiry_close    = round(float(closes[hit_sl_day - 1]), 4)
                                row.expiry_pnl_pct  = round(
                                    (closes[hit_sl_day - 1] / ref - 1) * 100, 2
                                )

                            elif len(closes) >= COMMON_MAX_HOLD:
                                # Survived 10 sessions without hitting TP or SL — EXPIRED.
                                # eval_exit_price = close of session 10 (same as expiry_close).
                                _expiry_close = round(float(closes[COMMON_MAX_HOLD - 1]), 4)
                                row.eval_hit_tp     = False
                                row.eval_hit_sl     = False
                                row.eval_status     = "EXPIRED"
                                row.eval_exit_price = _expiry_close
                                row.eval_pnl_pct    = round((_expiry_close / ref - 1) * 100, 2)
                                row.eval_hold_days  = COMMON_MAX_HOLD
                                row.eval_exit_date  = dates[COMMON_MAX_HOLD - 1].date()
                                row.expiry_close    = _expiry_close
                                row.expiry_pnl_pct  = row.eval_pnl_pct  # identical for EXPIRED

                            else:
                                # Still within hold window — check again tomorrow.
                                row.eval_status = "OPEN"

                            row.path_updated_at = datetime.now(timezone.utc)
                            updated += 1

                        except Exception:
                            logger.warning(
                                "comparison_update: error on %s row %d",
                                symbol, row.id, exc_info=True,
                            )

                    db.session.commit()

                except Exception:
                    db.session.rollback()
                    logger.warning("comparison_update: symbol %s failed", symbol, exc_info=True)

            logger.info("comparison_update: updated %d / %d rows", updated, len(pending))

        except Exception:
            logger.error("comparison_update: fatal error", exc_info=True)
