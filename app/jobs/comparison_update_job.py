"""
Comparison Update Job — fills forward-path fields in engine_comparison_logs.

Runs daily at 16:05 Cairo (5 min after outcome_job) on trading days (Sun–Thu).
For each OPEN comparison log entry from the past 10 trading days:
  1. Fetches OHLCV for the symbol (1-month window covers the hold period).
  2. Calculates fwd_1d/3d/5d/10d returns from entry_price.
  3. Calculates MFE and MAE over the hold period.
  4. Applies the Common Evaluation Layer:
       COMMON_TP = +7.0%   from entry_price
       COMMON_SL = -5.0%   from entry_price
       COMMON_MAX_HOLD = 10 trading days
     → eval_status = TP | SL | EXPIRED | OPEN
"""
import logging
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

COMMON_TP_PCT   = 7.0   # +7%
COMMON_SL_PCT   = 5.0   # -5% (stored as positive; applied as negative)
COMMON_MAX_HOLD = 10    # trading days


def run_comparison_update_job(app) -> None:
    with app.app_context():
        try:
            from app import db
            from app.models.engine_comparison_log import EngineComparisonLog
            from app.utils.data_fetcher import fetch_ohlcv

            today = date.today()
            cutoff = today - timedelta(days=16)  # covers 10 trading days + buffer

            pending = (
                EngineComparisonLog.query
                .filter(
                    EngineComparisonLog.signal_date >= cutoff,
                    EngineComparisonLog.eval_status.is_(None),
                    EngineComparisonLog.entry_price.isnot(None),
                )
                .all()
            )

            if not pending:
                logger.info("comparison_update: no pending logs to update")
                return

            logger.info("comparison_update: updating %d logs", len(pending))

            # Group by symbol to minimise yfinance calls
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
                            # Slice df to rows after signal_date
                            signal_dt = datetime.combine(row.signal_date, datetime.min.time())
                            future = df[df.index > signal_dt]
                            if future.empty:
                                continue  # data not yet available

                            closes = future[close_col].values
                            highs  = future[high_col].values
                            lows   = future[low_col].values
                            entry  = row.entry_price

                            # Forward returns
                            def _fwd(n):
                                if len(closes) >= n:
                                    return round((closes[n-1] / entry - 1) * 100, 2)
                                return None

                            row.fwd_1d_pct  = _fwd(1)
                            row.fwd_3d_pct  = _fwd(3)
                            row.fwd_5d_pct  = _fwd(5)
                            row.fwd_10d_pct = _fwd(10)

                            # MFE / MAE over COMMON_MAX_HOLD bars
                            hold_highs = highs[:COMMON_MAX_HOLD]
                            hold_lows  = lows[:COMMON_MAX_HOLD]
                            if len(hold_highs):
                                mfe = round((max(hold_highs) / entry - 1) * 100, 2)
                                mae = round((min(hold_lows)  / entry - 1) * 100, 2)
                                row.mfe_pct = mfe
                                row.mae_pct = mae
                                # Day index of MFE (0-based → 1-based)
                                row.days_to_mfe = int(hold_highs.tolist().index(max(hold_highs))) + 1

                            # Common Evaluation Layer
                            tp_thresh  = entry * (1 + COMMON_TP_PCT / 100)
                            sl_thresh  = entry * (1 - COMMON_SL_PCT / 100)
                            hold = min(COMMON_MAX_HOLD, len(closes))
                            hit_tp_day = hit_sl_day = None
                            for i in range(hold):
                                if hit_tp_day is None and highs[i] >= tp_thresh:
                                    hit_tp_day = i + 1
                                if hit_sl_day is None and lows[i] <= sl_thresh:
                                    hit_sl_day = i + 1
                                if hit_tp_day and hit_sl_day:
                                    break

                            if hit_tp_day and (hit_sl_day is None or hit_tp_day <= hit_sl_day):
                                row.eval_hit_tp    = True
                                row.eval_hit_sl    = False
                                row.eval_status    = "TP"
                                row.eval_pnl_pct   = COMMON_TP_PCT
                                row.eval_hold_days = hit_tp_day
                            elif hit_sl_day and (hit_tp_day is None or hit_sl_day < hit_tp_day):
                                row.eval_hit_tp    = False
                                row.eval_hit_sl    = True
                                row.eval_status    = "SL"
                                row.eval_pnl_pct   = -COMMON_SL_PCT
                                row.eval_hold_days = hit_sl_day
                            elif len(closes) >= COMMON_MAX_HOLD:
                                # Survived full hold → expired, use fwd_10d as outcome
                                row.eval_hit_tp    = False
                                row.eval_hit_sl    = False
                                row.eval_status    = "EXPIRED"
                                row.eval_pnl_pct   = row.fwd_10d_pct
                                row.eval_hold_days = COMMON_MAX_HOLD
                            else:
                                row.eval_status = "OPEN"  # still within hold window

                            row.path_updated_at = datetime.now(timezone.utc)
                            updated += 1

                        except Exception:
                            logger.warning(
                                "comparison_update: error for %s row %d",
                                symbol, row.id, exc_info=True,
                            )

                    db.session.commit()

                except Exception:
                    db.session.rollback()
                    logger.warning("comparison_update: symbol %s failed", symbol, exc_info=True)

            logger.info("comparison_update: updated %d / %d rows", updated, len(pending))

        except Exception:
            logger.error("comparison_update: fatal error", exc_info=True)
