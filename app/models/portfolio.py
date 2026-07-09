from datetime import datetime, timezone
from typing import Optional
from app import db


class PortfolioHolding(db.Model):
    """A single stock position — open or closed."""
    __tablename__ = "portfolio_holdings"

    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, nullable=True, index=True)   # NULL until Slice 3 auth
    stock_id  = db.Column(db.Integer, db.ForeignKey("stocks.id"), nullable=False, index=True)

    quantity   = db.Column(db.Float, nullable=False)       # number of shares
    avg_cost   = db.Column(db.Float, nullable=False)       # EGP per share
    currency   = db.Column(db.String(3), default="EGP")

    opened_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at   = db.Column(db.DateTime, nullable=True)
    close_price = db.Column(db.Float,    nullable=True)    # EGP per share at close

    notes = db.Column(db.Text, nullable=True)

    stock = db.relationship("Stock")

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    @property
    def cost_basis(self) -> float:
        return round(self.quantity * self.avg_cost, 2)

    @property
    def realized_pnl(self) -> Optional[float]:
        if self.closed_at is None or self.close_price is None:
            return None
        return round((self.close_price - self.avg_cost) * self.quantity, 2)

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "user_id":      self.user_id,
            "stock_id":     self.stock_id,
            "symbol":       self.stock.symbol if self.stock else None,
            "name_ar":      self.stock.name_ar if self.stock else None,
            "quantity":     self.quantity,
            "avg_cost":     self.avg_cost,
            "currency":     self.currency,
            "cost_basis":   self.cost_basis,
            "is_open":      self.is_open,
            "realized_pnl": self.realized_pnl,
            "opened_at":    self.opened_at.isoformat(),
            "closed_at":    self.closed_at.isoformat() if self.closed_at else None,
            "close_price":  self.close_price,
            "notes":        self.notes,
        }
