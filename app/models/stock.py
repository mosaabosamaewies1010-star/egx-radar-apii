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

    # Latest price snapshot (updated per bot run)
    last_price      = db.Column(db.Float,   nullable=True)
    last_change_pct = db.Column(db.Float,   nullable=True)
    last_volume     = db.Column(db.BigInteger, nullable=True)
    last_adt        = db.Column(db.Float,   nullable=True)   # Average Daily Turnover (EGP)

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
            "last_price":      self.last_price,
            "last_change_pct": self.last_change_pct,
            "last_volume":     self.last_volume,
            "last_adt":        self.last_adt,
            "price_updated_at": self.price_updated_at.isoformat() if self.price_updated_at else None,
        }
