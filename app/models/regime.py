from datetime import datetime, timezone
from app import db


class MarketRegimeHistory(db.Model):
    __tablename__ = "market_regime_history"

    id         = db.Column(db.Integer, primary_key=True)
    run_date   = db.Column(db.Date,    nullable=False, unique=True, index=True)

    regime     = db.Column(db.String(20), nullable=False)   # BULL|SIDEWAYS|BEAR|VOLATILE|LOW_LIQUIDITY
    confidence = db.Column(db.Float,      nullable=False)   # 0-100

    # Component scores
    ma_score       = db.Column(db.Float, nullable=True)   # EGX30 vs MAs (30pts)
    breadth_score  = db.Column(db.Float, nullable=True)   # Advance/Decline (25pts)
    adx_score      = db.Column(db.Float, nullable=True)   # Market ADX (20pts)
    volatility_score = db.Column(db.Float, nullable=True) # ATR% (15pts)
    volume_score   = db.Column(db.Float, nullable=True)   # Volume vs avg (10pts)

    # Breadth details
    advancing      = db.Column(db.Integer, nullable=True)
    declining      = db.Column(db.Integer, nullable=True)
    unchanged      = db.Column(db.Integer, nullable=True)

    # EGX30 snapshot
    egx30_close    = db.Column(db.Float, nullable=True)
    egx30_ma20     = db.Column(db.Float, nullable=True)
    egx30_ma50     = db.Column(db.Float, nullable=True)
    egx30_ma200    = db.Column(db.Float, nullable=True)

    # Human-readable reason (stored pre-generated)
    reason_ar  = db.Column(db.Text, nullable=True)
    reason_en  = db.Column(db.Text, nullable=True)

    calculated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "regime":     self.regime,
            "confidence": round(self.confidence, 1),
            "run_date":   self.run_date.isoformat(),
            "breadth": {
                "advancing": self.advancing,
                "declining": self.declining,
                "unchanged": self.unchanged,
            },
            "reason": {
                "ar": self.reason_ar,
                "en": self.reason_en,
            },
            "calculated_at": self.calculated_at.isoformat() if self.calculated_at else None,
        }
