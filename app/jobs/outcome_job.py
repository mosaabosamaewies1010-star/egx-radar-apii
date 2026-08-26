"""
Background job: auto-close PENDING opportunities.

Runs at 16:00 Cairo (90 min after EGX close) every trading day.
For each PENDING v1.0 opportunity it:
  1. Fetches the latest closing price via yfinance
  2. Checks TP1 / TP2 / SL levels
  3. Checks if max_hold_days has elapsed → EXPIRED
  4. Writes outcome + pnl_pct + hold_days + exit_reason + closed_at

Scope (Option A — 2026-08-27):
  Only processes strategy_version_id = v1.0.
  291 pre-v1.0 legacy signals (strategy_version_id = NULL) are not touched.
  Safety guard: aborts if v1.0 PENDING count exceeds MAX_EXPECTED_V1_PENDING.

Returns a summary dict — callers treat HTTP 200 as "job completed", not just "started".

Known specification note (2026-08-27):
  max_hold_days uses calendar days, not trading sessions.
  EGX trades Sun-Thu; a 10-calendar-day hold spans 6-8 trading sessions depending on entry day.
  Do NOT change this until the backtest spec (Stage/Trend Walk-Forward) is re-checked.
"""
import logging
from datetime import date, datetime, timezone as tz

logger = logging.getLogger(__name__)

# Safety guard: abort if v1.0 PENDING count unexpectedly exceeds this.
# Protects against regression where the v1.0 filter is accidentally removed
# or the population grows far beyond expected OOS size.
MAX_EXPECTED_V1_PENDING = 50


def _fetch_last_close(symbol: str) -> float | None:
    """Fetch the most recent closing price from Yahoo Finance (.CA suffix for EGX)."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{symbol}.CA")
        hist   = ticker.history(period="5d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        logger.warning("outcome_job: yfinance failed for %s", symbol, exc_info=True)
        return None


def _classify_exit(opp, last_price: float) -> tuple[str, str, float] | None:
    """
    Return (outcome, exit_reason, exit_price) or None if still open.

    Priority: TP2 > TP1 > SL > timeout
    None-safe: VOL_RADAR signals have tp1/tp2/sl = None — skip those checks,
    fall through to timeout only.
    """
    today = date.today()
    age   = (today - opp.run_date).days if opp.run_date else 0

    if opp.tp2_price is not None and last_price >= opp.tp2_price:
        return "WIN", "TP2", opp.tp2_price
    if opp.tp1_price is not None and last_price >= opp.tp1_price:
        return "WIN", "TP1", opp.tp1_price
    if opp.sl_price is not None and last_price <= opp.sl_price:
        return "LOSS", "SL", opp.sl_price
    if opp.max_hold_days and age >= opp.max_hold_days:
        return "EXPIRED", "timeout", last_price
    return None


def _profile_used(opp, exit_reason: str) -> str | None:
    """For dual-profile opps (SRA, TREND), determine which exit profile was hit."""
    if not (opp.opp_type or "").startswith(("SRA_", "TREND_")):
        return None
    if exit_reason == "TP1":
        return "FAST"
    if exit_reason == "TP2":
        return "BALANCED"
    return None


def run_outcome_job(app) -> dict:
    """
    Auto-close PENDING v1.0 opportunities and return an execution summary.

    HTTP 200 on /api/admin/trigger-outcome means this function completed —
    not merely that a background thread was started.

    Summary fields:
      started_at, finished_at, duration_seconds
      pending_before, pending_after
      scanned, closed, tp1, tp2, sl, timeout, skipped, errors
      status: ok | ok_nothing_to_close | ok_with_errors |
              suspicious_zero_closed | aborted_safety_cap |
              aborted_v1_not_found | error
    """
    started_at = datetime.now(tz.utc)

    summary: dict = {
        "started_at":          started_at.isoformat(),
        "finished_at":         None,
        "duration_seconds":    0,
        "strategy_version_id": None,
        "pending_before":      None,
        "pending_after":       None,
        "pending_legacy":      None,
        "scanned":             0,
        "closed":              0,
        "tp1":                 0,
        "tp2":                 0,
        "sl":                  0,
        "timeout":             0,
        "skipped":             0,
        "errors":              0,
        "status":              "running",
    }

    with app.app_context():
        try:
            from app import db
            from app.models.opportunity import Opportunity
            from app.models.strategy_version import StrategyVersion

            # Resolve v1.0 ID at runtime.
            # Exactly 1 row expected — 0 = missing, 2+ = ambiguous (both abort).
            v1_rows = StrategyVersion.query.filter_by(version="v1.0").all()
            if len(v1_rows) == 0:
                logger.error("outcome_job: strategy_version v1.0 not found in DB — aborting")
                summary["status"] = "aborted_v1_not_found"
            elif len(v1_rows) > 1:
                logger.error(
                    "outcome_job: ambiguous — %d rows found for version='v1.0'. "
                    "Aborting to avoid processing wrong population.",
                    len(v1_rows),
                )
                summary["status"] = "aborted_v1_ambiguous"
            else:
                v1_id = v1_rows[0].id
                summary["strategy_version_id"] = v1_id

                # Informational count — legacy signals (NULL strategy_version_id).
                # Never processed by this job.
                summary["pending_legacy"] = (
                    Opportunity.query
                    .filter(
                        Opportunity.outcome == "PENDING",
                        Opportunity.strategy_version_id.is_(None),
                    )
                    .count()
                )

                pending = (
                    Opportunity.query
                    .filter(
                        Opportunity.outcome == "PENDING",
                        Opportunity.strategy_version_id == v1_id,
                    )
                    .all()
                )

                summary["pending_before"] = len(pending)
                summary["scanned"]        = len(pending)

                # Safety guard: unexpected population size
                if len(pending) > MAX_EXPECTED_V1_PENDING:
                    logger.error(
                        "outcome_job: SAFETY GUARD — v1.0 PENDING count=%d exceeds cap=%d. "
                        "Aborting to prevent unintended bulk processing.",
                        len(pending), MAX_EXPECTED_V1_PENDING,
                    )
                    summary["status"] = "aborted_safety_cap"

                elif not pending:
                    logger.info("outcome_job: no PENDING v1.0 opportunities")
                    summary["status"]       = "ok_nothing_to_close"
                    summary["pending_after"] = 0

                else:
                    today = date.today()

                    overdue_count = sum(
                        1 for opp in pending
                        if opp.max_hold_days and (today - opp.run_date).days >= opp.max_hold_days
                    )
                    logger.info(
                        "outcome_job: checking %d v1.0 PENDING | %d overdue (age >= max_hold_days)",
                        len(pending), overdue_count,
                    )

                    tp1_c = tp2_c = sl_c = timeout_c = skipped = errors = closed = 0

                    for opp in pending:
                        try:
                            sym        = opp.stock.symbol if opp.stock else "?"
                            last_price = _fetch_last_close(sym)

                            if last_price is None:
                                skipped += 1
                                logger.debug("outcome_job: no price for %s — skipped", sym)
                                continue

                            result = _classify_exit(opp, last_price)
                            if result is None:
                                skipped += 1
                                continue

                            outcome, exit_reason, exit_price = result
                            hold_days = max(0, (today - opp.run_date).days) if opp.run_date else None
                            pnl_pct   = round(
                                (exit_price - opp.entry_price) / opp.entry_price * 100, 2
                            )

                            opp.outcome     = outcome
                            opp.exit_reason = exit_reason
                            opp.exit_price  = exit_price
                            opp.pnl_pct     = pnl_pct
                            opp.hold_days   = hold_days
                            opp.closed_at   = today
                            opp.is_active   = False

                            profile = _profile_used(opp, exit_reason)
                            if profile and opp.feature_snapshot:
                                snap = dict(opp.feature_snapshot)
                                snap["profile_used"]   = profile
                                snap["closed_pnl_pct"] = pnl_pct
                                opp.feature_snapshot   = snap

                            db.session.commit()

                            closed += 1
                            if exit_reason == "TP1":       tp1_c     += 1
                            elif exit_reason == "TP2":     tp2_c     += 1
                            elif exit_reason == "SL":      sl_c      += 1
                            elif exit_reason == "timeout": timeout_c += 1

                            logger.info(
                                "outcome_job: %s → %s (%s%s pnl=%.2f%% hold=%sd)",
                                sym, outcome, exit_reason,
                                f" [{profile}]" if profile else "",
                                pnl_pct, hold_days,
                            )

                        except Exception:
                            db.session.rollback()
                            errors += 1
                            try:
                                sym_label = opp.stock.symbol if opp.stock else "?"
                            except Exception:
                                sym_label = "?"
                            logger.warning(
                                "outcome_job: error processing %s", sym_label, exc_info=True
                            )

                    # Re-query after commits for accurate pending_after count
                    summary["pending_after"] = (
                        Opportunity.query
                        .filter(
                            Opportunity.outcome == "PENDING",
                            Opportunity.strategy_version_id == v1_id,
                        )
                        .count()
                    )

                    summary.update({
                        "closed":  closed,
                        "tp1":     tp1_c,
                        "tp2":     tp2_c,
                        "sl":      sl_c,
                        "timeout": timeout_c,
                        "skipped": skipped,
                        "errors":  errors,
                    })

                    if overdue_count > 0 and closed == 0 and errors == 0:
                        logger.warning(
                            "outcome_job: SUSPICIOUS — %d overdue but 0 closed, 0 errors. "
                            "Requires investigation.",
                            overdue_count,
                        )
                        summary["status"] = "suspicious_zero_closed"
                    elif errors > 0:
                        summary["status"] = "ok_with_errors"
                    else:
                        summary["status"] = "ok"

                    logger.info(
                        "outcome_job: DONE scanned=%d closed=%d "
                        "(tp1=%d tp2=%d sl=%d timeout=%d) skipped=%d errors=%d "
                        "pending_before=%d pending_after=%d status=%s",
                        len(pending), closed,
                        tp1_c, tp2_c, sl_c, timeout_c,
                        skipped, errors,
                        summary["pending_before"], summary["pending_after"],
                        summary["status"],
                    )

        except Exception as _top_exc:
            logger.exception("outcome_job: top-level error")
            summary["status"] = "error"

        finished = datetime.now(tz.utc)
        summary["finished_at"]      = finished.isoformat()
        summary["duration_seconds"] = round((finished - started_at).total_seconds())

    return summary
