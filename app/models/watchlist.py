from datetime import datetime, timezone
from app import db


class Watchlist(db.Model):
    """User watchlist — stock symbols the user is tracking."""
    __tablename__ = "watchlists"

    id       = db.Column(db.Integer, primary_key=True)
    user_id  = db.Column(db.Integer, nullable=True, index=True)   # NULL until Slice 3 auth
    stock_id = db.Column(db.Integer, db.ForeignKey("stocks.id"), nullable=False, index=True)

    notes              = db.Column(db.Text,  nullable=True)
    alert_price_above  = db.Column(db.Float, nullable=True)   # trigger notification when price > this
    alert_price_below  = db.Column(db.Float, nullable=True)   # trigger notification when price < this

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    stock = db.relationship("Stock")

    def to_dict(self) -> dict:
        return {
            "id":                 self.id,
            "user_id":            self.user_id,
            "stock_id":           self.stock_id,
            "symbol":             self.stock.symbol if self.stock else None,
            "name_ar":            self.stock.name_ar if self.stock else None,
            "notes":              self.notes,
            "alert_price_above":  self.alert_price_above,
            "alert_price_below":  self.alert_price_below,
            "created_at":         self.created_at.isoformat(),
        }
