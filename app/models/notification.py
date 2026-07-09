from datetime import datetime, timezone
from app import db

NOTIFICATION_TYPES = (
    "score_change",    # Radar Score moved > 10 pts for a watchlisted stock
    "new_opportunity", # New opportunity detected for a watchlisted stock
    "sl_alert",        # Price within 2% of stop loss level
    "tp_reached",      # TP1 or TP2 hit for an open opportunity
    "regime_change",   # Market regime changed since last run
    "morning_brief",   # Daily morning brief is ready
)


class Notification(db.Model):
    """Push/in-app notification for a user."""
    __tablename__ = "notifications"

    id       = db.Column(db.Integer, primary_key=True)
    user_id  = db.Column(db.Integer, nullable=True, index=True)   # NULL until Slice 3 auth
    stock_id = db.Column(db.Integer, db.ForeignKey("stocks.id"), nullable=True)

    type     = db.Column(db.String(50),  nullable=False)
    title_ar = db.Column(db.String(300), nullable=False)
    body_ar  = db.Column(db.Text,        nullable=True)

    is_read    = db.Column(db.Boolean,  default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    stock = db.relationship("Stock")

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "user_id":    self.user_id,
            "type":       self.type,
            "title_ar":   self.title_ar,
            "body_ar":    self.body_ar,
            "symbol":     self.stock.symbol if self.stock else None,
            "is_read":    self.is_read,
            "created_at": self.created_at.isoformat(),
        }
