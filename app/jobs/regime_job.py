"""
Background job: compute market regime from EGX30 and persist to DB.
Runs at 15:00 Cairo (30 min after market close).
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)


def run_regime_job(app) -> None:
    with app.app_context():
        try:
            from app import db
            from app.services.market_regime import compute_market_regime
            from app.models.regime import MarketRegimeHistory

            result = compute_market_regime()
            if result is None:
                logger.error("regime_job: compute_market_regime returned None — no data from yfinance")
                return

            today = date.today()
            existing = MarketRegimeHistory.query.filter_by(run_date=today).first()

            if existing:
                existing.regime     = result.regime
                existing.confidence = result.confidence
                existing.advancing  = result.advancing
                existing.declining  = result.declining
                existing.unchanged  = result.unchanged
                existing.egx30_close = result.egx30_close
            else:
                db.session.add(MarketRegimeHistory(
                    run_date    = today,
                    regime      = result.regime,
                    confidence  = result.confidence,
                    advancing   = result.advancing,
                    declining   = result.declining,
                    unchanged   = result.unchanged,
                    egx30_close = result.egx30_close,
                ))

            db.session.commit()
            logger.info(
                "regime_job: persisted %s (confidence=%.1f, EGX30=%.1f)",
                result.regime, result.confidence, result.egx30_close,
            )

        except Exception:
            logger.exception("regime_job: unhandled error")
