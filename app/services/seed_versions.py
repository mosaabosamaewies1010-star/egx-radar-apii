"""
Idempotent seed for StrategyVersion registry.
Called once on app startup — safe to call multiple times.
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)

_V1_VERSION     = "v1.0"
_V1_DESCRIPTION = (
    "Core Engine v1.0 (FROZEN) — 3-tier priority:\n"
    "1. Stage Breakout ⭐⭐⭐⭐⭐ (backtest PF 2.075)\n"
    "2. Trend Initiation A+/A ⭐⭐⭐⭐ (backtest PF 1.644)\n"
    "3. Volume Radar ⭐⭐⭐ (watch-only, no buy signal)\n"
    "OOS tracking started 2026-07-25."
)
_V1_DATE = date(2026, 7, 25)


def seed_strategy_versions(app) -> None:
    """Ensure v1.0 row exists in strategy_versions. Safe to call on every restart."""
    with app.app_context():
        try:
            from app import db
            from app.models.strategy_version import StrategyVersion

            existing = StrategyVersion.query.filter_by(version=_V1_VERSION).first()
            if existing:
                return

            db.session.add(StrategyVersion(
                version        = _V1_VERSION,
                description    = _V1_DESCRIPTION,
                effective_from = _V1_DATE,
                effective_to   = None,   # still current
            ))
            db.session.commit()
            logger.info("seed_versions: registered %s (OOS start %s)", _V1_VERSION, _V1_DATE)
        except Exception:
            logger.exception("seed_versions: failed to seed strategy versions")
