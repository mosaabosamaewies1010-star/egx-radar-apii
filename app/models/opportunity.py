from datetime import datetime, timezone
from app import db


class Opportunity(db.Model):
    __tablename__ = "opportunities"

    id         = db.Column(db.Integer, primary_key=True)
    stock_id   = db.Column(db.Integer, db.ForeignKey("stocks.id"), nullable=False, index=True)
    run_date   = db.Column(db.Date,    nullable=False, index=True)

    # Opportunity type
    opp_type   = db.Column(db.String(50), nullable=True)   # Breakout|Momentum|Swing|Sharia|etc.

    # Levels (from Quant Bible formulas)
    entry_price   = db.Column(db.Float, nullable=False)
    tp1_price     = db.Column(db.Float, nullable=False)
    tp2_price     = db.Column(db.Float, nullable=False)
    sl_price      = db.Column(db.Float, nullable=False)
    rr_ratio      = db.Column(db.Float, nullable=True)   # R/R to TP1
    max_hold_days = db.Column(db.Integer, default=12)

    # Score at signal time
    radar_score    = db.Column(db.Float, nullable=False)
    signal_quality = db.Column(db.String(20), nullable=True)  # HIGH|MEDIUM|LOW

    # ── Decision Moat: immutable snapshot of ALL context at signal time ──────
    # Frozen the moment the opportunity is created — never updated even if
    # source data is later corrected. Enables faithful replay of past decisions.
    feature_snapshot = db.Column(db.JSON, nullable=True)
    # Example keys: rsi, adx, mfi, rvol, regime, breadth_pct, sector_rank,
    #   contrib_ema_trend, contrib_rsi, contrib_bb_breakout, contrib_obv,
    #   contrib_adx, contrib_vol_surge, contrib_bb_squeeze, contrib_mfi,
    #   contrib_rel_strength, atr, support, resistance, score_pct

    # Strategy version that generated this opportunity
    strategy_version_id = db.Column(
        db.Integer, db.ForeignKey("strategy_versions.id"), nullable=True, index=True
    )
    strategy_version = db.relationship("StrategyVersion", back_populates="opportunities")

    # Outcome tracking (filled when position closes)
    outcome     = db.Column(db.String(20), nullable=True)  # WIN|LOSS|PENDING|EXPIRED
    closed_at   = db.Column(db.Date,       nullable=True)
    exit_price  = db.Column(db.Float,      nullable=True)
    exit_reason = db.Column(db.String(30), nullable=True)  # TP1|TP2|SL|MANUAL|EXPIRED
    pnl_pct     = db.Column(db.Float,      nullable=True)
    hold_days   = db.Column(db.Integer,    nullable=True)  # actual days held

    is_active   = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    stock = db.relationship("Stock", back_populates="opportunities")

    @property
    def is_sra(self) -> bool:
        return self.opp_type is not None and self.opp_type.startswith("SRA_")

    def to_dict(self) -> dict:
        snap = self.feature_snapshot or {}
        base = {
            "id":             self.id,
            "symbol":         self.stock.symbol,
            "name_ar":        self.stock.name_ar,
            "run_date":       self.run_date.isoformat(),
            "type":           self.opp_type,
            "radar_score":    self.radar_score,
            "signal_quality": self.signal_quality,
            "levels": {
                "entry": self.entry_price,
                "tp1":   self.tp1_price,
                "tp2":   self.tp2_price,
                "sl":    self.sl_price,
                "rr":    round(self.rr_ratio, 2) if self.rr_ratio else None,
                "max_hold_days": self.max_hold_days,
            },
            "outcome":          self.outcome,
            "exit_reason":      self.exit_reason,
            "pnl_pct":          self.pnl_pct,
            "hold_days":        self.hold_days,
            "strategy_version": self.strategy_version.version if self.strategy_version else None,
            "feature_snapshot": snap,
        }

        # SRA-specific top-level fields — consumed by frontend cards
        if self.is_sra:
            profiles = snap.get("profiles", {})
            base["sra"] = {
                "score":            snap.get("sra_score"),
                "grade":            snap.get("sra_grade"),
                "setup":            snap.get("setup"),
                "rvol_spike":       snap.get("rvol_spike"),
                "rsi_at_low":       snap.get("rsi_at_low"),
                "regime":           snap.get("regime"),
                "market_breadth":   snap.get("market_breadth_pct"),
                "sector_positive":  snap.get("sector_slope_positive"),
                "signals":          snap.get("signals", []),
                "similar_cases":    snap.get("similar_cases", 0),
                "win_rate":         snap.get("historical_win_rate", 0.0),
                "avg_return":       snap.get("avg_return", 0.0),
                "exit_profiles": {
                    "FAST": {
                        "target_pct": 7.0,
                        "target_price": profiles.get("FAST", {}).get("tp"),
                        "sl_price":     profiles.get("FAST", {}).get("sl"),
                        "max_bars":     profiles.get("FAST", {}).get("max_bars", 5),
                    },
                    "BALANCED": {
                        "target_pct": 15.0,
                        "target_price": profiles.get("BALANCED", {}).get("tp"),
                        "sl_price":     profiles.get("BALANCED", {}).get("sl"),
                        "max_bars":     profiles.get("BALANCED", {}).get("max_bars", 10),
                    },
                },
            }

        return base
