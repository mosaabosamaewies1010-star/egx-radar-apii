import uuid
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from app import db


def _gen_ref_code() -> str:
    return uuid.uuid4().hex[:8].upper()


class User(db.Model):
    __tablename__ = "users"

    id               = db.Column(db.Integer, primary_key=True)
    email            = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash    = db.Column(db.String(255), nullable=False)
    name             = db.Column(db.String(100), nullable=True)

    is_active        = db.Column(db.Boolean, default=True,  nullable=False)
    is_pro           = db.Column(db.Boolean, default=False, nullable=False)

    referral_code          = db.Column(db.String(20), unique=True, nullable=True, index=True)
    referred_by_id         = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    referral_discount_used = db.Column(db.Boolean, default=False, nullable=False)  # خصم الدعوة استُخدم
    discount_credits       = db.Column(db.Integer, default=0, nullable=False)       # مكافآت الشخص الداعي

    created_at    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login_at = db.Column(db.DateTime, nullable=True)

    referred_by = db.relationship("User", remote_side="User.id", foreign_keys=[referred_by_id])

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def ensure_referral_code(self) -> str:
        if not self.referral_code:
            self.referral_code = _gen_ref_code()
        return self.referral_code

    def has_referral_discount(self) -> bool:
        """هل لديه خصم دعوة لم يستخدمه بعد؟"""
        return bool(self.referred_by_id and not self.referral_discount_used)

    def to_dict(self) -> dict:
        return {
            "id":                    self.id,
            "email":                 self.email,
            "name":                  self.name,
            "is_pro":                self.is_pro,
            "referral_code":         self.referral_code,
            "discount_credits":      self.discount_credits,
            "referred_by_id":        self.referred_by_id,
            "has_referral_discount": self.has_referral_discount(),
            "created_at":            self.created_at.isoformat(),
        }
