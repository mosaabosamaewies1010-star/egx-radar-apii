from datetime import datetime, timezone
from app import db


class RadarScoreHistory(db.Model):
    """One record per stock per bot run — enables delta/trend calculation."""
    __tablename__ = "radar_score_history"

    id         = db.Column(db.Integer, primary_key=True)
    stock_id   = db.Column(db.Integer, db.ForeignKey("stocks.id"), nullable=False, index=True)
    run_date   = db.Column(db.Date,    nullable=False, index=True)

    # Final score
    score      = db.Column(db.Float, nullable=False)

    # Component breakdown (for WhyThisScore / Explain Engine)
    trend_score       = db.Column(db.Float, nullable=True)
    momentum_score    = db.Column(db.Float, nullable=True)
    liquidity_score   = db.Column(db.Float, nullable=True)
    volume_score      = db.Column(db.Float, nullable=True)
    sector_score      = db.Column(db.Float, nullable=True)
    fundamental_score = db.Column(db.Float, nullable=True)
    risk_penalty      = db.Column(db.Float, nullable=True)
    regime_multiplier = db.Column(db.Float, nullable=True)

    # Raw indicator values (stored for explain engine + debugging)
    adx        = db.Column(db.Float, nullable=True)
    rsi        = db.Column(db.Float, nullable=True)
    macd       = db.Column(db.Float, nullable=True)
    macd_signal= db.Column(db.Float, nullable=True)
    atr_pct    = db.Column(db.Float, nullable=True)
    rvol       = db.Column(db.Float, nullable=True)
    ma20       = db.Column(db.Float, nullable=True)
    ma50       = db.Column(db.Float, nullable=True)
    ma200      = db.Column(db.Float, nullable=True)
    obv_trend  = db.Column(db.String(10), nullable=True)   # "UP" | "DOWN" | "FLAT"

    # Explain text (pre-generated, stored to avoid re-computation)
    explain_ar = db.Column(db.Text, nullable=True)
    explain_en = db.Column(db.Text, nullable=True)

    # Signal quality
    data_quality = db.Column(db.String(20), nullable=True)  # HIGH | MEDIUM | LOW | NO_DATA

    calculated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    stock = db.relationship("Stock", back_populates="scores")

    __table_args__ = (
        db.UniqueConstraint("stock_id", "run_date", name="uq_score_stock_date"),
    )

    def to_dict(self) -> dict:
        return {
            "score":            round(self.score, 1),
            "run_date":         self.run_date.isoformat(),
            "breakdown": {
                "trend":       self.trend_score,
                "momentum":    self.momentum_score,
                "liquidity":   self.liquidity_score,
                "volume":      self.volume_score,
                "sector":      self.sector_score,
                "fundamental": self.fundamental_score,
                "risk_penalty":      self.risk_penalty,
                "regime_multiplier": self.regime_multiplier,
            },
            "indicators": {
                "adx":        self.adx,
                "rsi":        self.rsi,
                "atr_pct":    self.atr_pct,
                "rvol":       self.rvol,
                "obv_trend":  self.obv_trend,
            },
            "explain": {
                "ar": self.explain_ar,
                "en": self.explain_en,
            },
            "data_quality": self.data_quality,
        }
