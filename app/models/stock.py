from datetime import datetime, timezone
from app import db


class Stock(db.Model):
    """Static stock metadata — fetched once, updated weekly."""
    __tablename__ = "stocks"

    id          = db.Column(db.Integer, primary_key=True)
    symbol      = db.Column(db.String(20),  unique=True, nullable=False, index=True)
    name_ar     = db.Column(db.String(200), nullable=False)
    name_en     = db.Column(db.String(200), nullable=True)
    sector      = db.Column(db.String(100), nullable=True)
    is_sharia   = db.Column(db.Boolean,     default=False)
    is_active   = db.Column(db.Boolean,     default=True)

    # Fundamentals (updated weekly)
    pe_ratio    = db.Column(db.Float, nullable=True)
    eps_growth  = db.Column(db.Float, nullable=True)   # % YoY
    dividend_yield = db.Column(db.Float, nullable=True)
    debt_equity = db.Column(db.Float, nullable=True)
    market_cap  = db.Column(db.BigInteger, nullable=True)
    eps         = db.Column(db.Float, nullable=True)   # trailing 12-month EPS (EGP/share)
    week52_high = db.Column(db.Float, nullable=True)
    week52_low  = db.Column(db.Float, nullable=True)
    book_value  = db.Column(db.Float, nullable=True)   # EGP/share

    # Latest price snapshot (updated per bot run)
    last_price      = db.Column(db.Float,   nullable=True)
    last_change_pct = db.Column(db.Float,   nullable=True)
    last_change_amt = db.Column(db.Float,   nullable=True)
    last_volume     = db.Column(db.BigInteger, nullable=True)
    last_adt        = db.Column(db.Float,   nullable=True)   # Average Daily Turnover (EGP)
    day_open        = db.Column(db.Float,   nullable=True)
    day_high        = db.Column(db.Float,   nullable=True)
    day_low         = db.Column(db.Float,   nullable=True)

    fundamentals_updated_at = db.Column(db.DateTime, nullable=True)
    price_updated_at        = db.Column(db.DateTime, nullable=True)
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    scores       = db.relationship("RadarScoreHistory", back_populates="stock", lazy="dynamic")
    opportunities = db.relationship("Opportunity",      back_populates="stock", lazy="dynamic")

    def to_dict(self) -> dict:
        return {
            "symbol":          self.symbol,
            "name_ar":         self.name_ar,
            "name_en":         self.name_en,
            "sector":          self.sector,
            "is_sharia":       self.is_sharia,
            "pe_ratio":        self.pe_ratio,
            "eps_growth":      self.eps_growth,
            "dividend_yield":  self.dividend_yield,
            "debt_equity":     self.debt_equity,
            "market_cap":      self.market_cap,
            "eps":             self.eps,
            "week52_high":     self.week52_high,
            "week52_low":      self.week52_low,
            "book_value":      self.book_value,
            "last_price":      self.last_price,
            "last_change_pct": self.last_change_pct,
            "last_change_amt": self.last_change_amt,
            "last_volume":     self.last_volume,
            "last_adt":        self.last_adt,
            "day_open":        self.day_open,
            "day_high":        self.day_high,
            "day_low":         self.day_low,
            "fundamentals_updated_at": self.fundamentals_updated_at.isoformat() if self.fundamentals_updated_at else None,
            "price_updated_at": self.price_updated_at.isoformat() if self.price_updated_at else None,
        }
