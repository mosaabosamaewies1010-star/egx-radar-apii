"""
Background job: auto-close PENDING opportunities.

Runs at 16:00 Cairo (90 min after EGX close) every trading day.
For each PENDING opportunity it:
  1. Fetches the latest closing price via yfinance
  2. Checks TP1 / TP2 / SL levels
  3. Checks if max_hold_days has elapsed → EXPIRED
  4. Writes outcome + pnl_pct + hold_days + exit_reason + closed_at
"""
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_EXIT_MAP = {
    "TP2": ("WIN",  "TP2"),
    "TP1": ("WIN",  "TP1"),
    "SL":  ("LOSS", "SL"),
}


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
    For SRA: TP1 = FAST target (7%), TP2 = BALANCED target (15%).
    """
    today = date.today()
    age   = (today - opp.run_date).days if opp.run_date else 0

    if last_price >= opp.tp2_price:
        return "WIN", "TP2", opp.tp2_price
    if last_price >= opp.tp1_price:
        return "WIN", "TP1", opp.tp1_price
    if last_price <= opp.sl_price:
        return "LOSS", "SL", opp.sl_price
    if age >= opp.max_hold_days:
        return "EXPIRED", "timeout", last_price
    return None


def _profile_used(opp, exit_reason: str) -> str | None:
    """For dual-profile opps (SRA, TREND), determine which exit profile was hit.
    Both use TP1 = FAST target (7%) and TP2 = BALANCED target (15%)."""
    if not (opp.opp_type or "").startswith(("SRA_", "TREND_")):
        return None
    if exit_reason == "TP1":
        return "FAST"
    if exit_reason == "TP2":
        return "BALANCED"
    return None


def run_outcome_job(app) -> None:
    with app.app_context():
        try:
            from app import db
            from app.models.opportunity import Opportunity

            pending = (
                Opportunity.query
                .filter(Opportunity.outcome == "PENDING")
                .all()
            )

            if not pending:
                logger.info("outcome_job: no PENDING opportunities")
                return

            logger.info("outcome_job: checking %d PENDING opportunities", len(pending))
            closed = 0

            for opp in pending:
                sym = opp.stock.symbol
                last_price = _fetch_last_close(sym)
                if last_price is None:
                    continue

                result = _classify_exit(opp, last_price)
                if result is None:
                    continue

                outcome, exit_reason, exit_price = result
                today    = date.today()
                hold_days = max(0, (today - opp.run_date).days) if opp.run_date else None
                pnl_pct  = round((exit_price - opp.entry_price) / opp.entry_price * 100, 2)

                opp.outcome     = outcome
                opp.exit_reason = exit_reason
                opp.exit_price  = exit_price
                opp.pnl_pct     = pnl_pct
                opp.hold_days   = hold_days
                opp.closed_at   = today
                opp.is_active   = False

                # For SRA: record which exit profile was used in the snapshot
                profile = _profile_used(opp, exit_reason)
                if profile and opp.feature_snapshot:
                    snap = dict(opp.feature_snapshot)
                    snap["profile_used"] = profile
                    snap["closed_pnl_pct"] = pnl_pct
                    opp.feature_snapshot = snap

                closed += 1
                logger.info(
                    "outcome_job: %s → %s (%s%s, pnl=%.2f%%, hold=%sd)",
                    sym, outcome, exit_reason,
                    f" [{profile}]" if profile else "",
                    pnl_pct, hold_days,
                )

            db.session.commit()
            logger.info("outcome_job: closed %d / %d opportunities", closed, len(pending))

        except Exception:
            logger.exception("outcome_job: top-level error")
