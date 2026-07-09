from datetime import datetime, timezone
from app import db

PLANS = {
    "pro_monthly": {
        "id":       "pro_monthly",
        "name_ar":  "PRO شهري",
        "price":    299.0,
        "currency": "EGP",
        "period":   "monthly",
        "savings":  None,
    },
    "pro_annual": {
        "id":       "pro_annual",
        "name_ar":  "PRO سنوي",
        "price":    2699.0,
        "currency": "EGP",
        "period":   "annual",
        "savings":  "25%",
    },
}

PLAN_FEATURES = [
    "EGX Radar لجميع الأسهم",
    "تنبيهات فورية",
    "فرص التداول",
    "الموجز الصباحي",
    "مؤشرات متقدمة (RSI · ADX · RVOL)",
    "دعم أولوي",
]

PAYMENT_STATUSES = ("pending", "completed", "failed", "refunded")


class Payment(db.Model):
    """PRO subscription payment record."""
    __tablename__ = "payments"

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    plan         = db.Column(db.String(50),  nullable=False)   # pro_monthly | pro_annual
    amount       = db.Column(db.Float,       nullable=False)
    currency     = db.Column(db.String(3),   default="EGP", nullable=False)
    status       = db.Column(db.String(20),  default="pending", nullable=False)
    provider_ref = db.Column(db.String(100), nullable=True)    # payment gateway reference
    created_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user = db.relationship("User")

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "user_id":      self.user_id,
            "plan":         self.plan,
            "amount":       self.amount,
            "currency":     self.currency,
            "status":       self.status,
            "provider_ref": self.provider_ref,
            "created_at":   self.created_at.isoformat(),
        }
