from datetime import datetime, timezone
from app import db


class StrategyVersion(db.Model):
    """
    Immutable registry of every algorithm version that generated signals.
    Each Opportunity references the version that created it so performance
    can be sliced by version over time.
    """
    __tablename__ = "strategy_versions"

    id             = db.Column(db.Integer, primary_key=True)
    version        = db.Column(db.String(30), nullable=False, unique=True)   # e.g. "v4.0", "backtest_v1"
    description    = db.Column(db.Text, nullable=True)
    effective_from = db.Column(db.Date, nullable=False)
    effective_to   = db.Column(db.Date, nullable=True)   # NULL = still current
    created_at     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    opportunities  = db.relationship("Opportunity", back_populates="strategy_version", lazy="dynamic")

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "version":        self.version,
            "description":    self.description,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to":   self.effective_to.isoformat()   if self.effective_to   else None,
        }
