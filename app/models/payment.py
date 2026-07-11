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

PAYMENT_STATUSES  = ("pending", "completed", "failed", "refunded", "rejected")
PAYMENT_METHODS   = ("instapay", "vodafone_cash")

PAYMENT_METHOD_LABELS = {
    "instapay":      "InstaPay",
    "vodafone_cash": "Vodafone Cash",
}

# Account numbers shown to the user during checkout
PAYMENT_ACCOUNTS = {
    "instapay":      "01XXXXXXXXXX",   # ← ضع رقمك هنا
    "vodafone_cash": "01XXXXXXXXXX",   # ← ضع رقمك هنا
}


class Payment(db.Model):
    """PRO subscription payment record."""
    __tablename__ = "payments"

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    plan           = db.Column(db.String(50),  nullable=False)
    amount         = db.Column(db.Float,       nullable=False)
    currency       = db.Column(db.String(3),   default="EGP", nullable=False)
    status         = db.Column(db.String(20),  default="pending", nullable=False)
    provider_ref   = db.Column(db.String(100), nullable=True)
    payment_method = db.Column(db.String(30),  nullable=True)   # instapay | vodafone_cash
    receipt_image  = db.Column(db.Text,        nullable=True)   # base64 data-url
    admin_note     = db.Column(db.Text,        nullable=True)   # رسالة الرفض
    created_at     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user = db.relationship("User")

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "user_id":        self.user_id,
            "plan":           self.plan,
            "amount":         self.amount,
            "currency":       self.currency,
            "status":         self.status,
            "provider_ref":   self.provider_ref,
            "payment_method": self.payment_method,
            "has_receipt":    bool(self.receipt_image),
            "admin_note":     self.admin_note,
            "created_at":     self.created_at.isoformat(),
        }

    def to_dict_admin(self) -> dict:
        """Full dict including receipt image — for admin only."""
        d = self.to_dict()
        d["receipt_image"] = self.receipt_image
        d["user_email"]    = self.user.email  if self.user else None
        d["user_name"]     = self.user.name   if self.user else None
        return d
