"""
Engine Comparison Log — canonical record for Engine Comparison v1.

One row per (signal_date, symbol, engine). Written by daily_scan.py immediately
after each engine commits its Opportunity. Forward-path fields are filled later
by comparison_update_job (runs at 16:05 Cairo after markets close).

Common Evaluation Layer applies the same success definition to all engines:
    COMMON_TP = +7.0%  from entry_price  (first bar entry_price crosses this → TP1)
    COMMON_SL = -5.0%  from entry_price  (first bar entry_price crosses this → SL)
    COMMON_MAX_HOLD = 10 trading days
This is separate from each engine's own native tp/sl, which are also stored.
"""
from datetime import datetime, timezone
from app import db


class EngineComparisonLog(db.Model):
    __tablename__ = "engine_comparison_logs"

    id          = db.Column(db.Integer, primary_key=True)
    setup_id    = db.Column(db.String(32), nullable=False, index=True)   # YYYYMMDD_SYMBOL
    signal_date = db.Column(db.Date, nullable=False, index=True)
    symbol      = db.Column(db.String(20), nullable=False, index=True)
    engine      = db.Column(db.String(20), nullable=False)               # STAGE|TREND|VOL_RADAR|SRA
    signal_type = db.Column(db.String(40), nullable=True)                # STAGE_STRONG, SRA_A+, …

    opportunity_id = db.Column(
        db.Integer, db.ForeignKey("opportunities.id"), nullable=True, index=True
    )

    # ── Engine native levels ───────────────────────────────────────────────────
    entry_price   = db.Column(db.Float, nullable=True)
    tp1_price     = db.Column(db.Float, nullable=True)
    tp2_price     = db.Column(db.Float, nullable=True)
    sl_price      = db.Column(db.Float, nullable=True)
    rr_ratio      = db.Column(db.Float, nullable=True)
    max_hold_days = db.Column(db.Integer, nullable=True)

    # ── Score / grade at signal time ───────────────────────────────────────────
    score = db.Column(db.Float, nullable=True)    # engine-specific 0-100 or raw
    grade = db.Column(db.String(10), nullable=True)  # A+/A/STRONG/DEVELOPING/…

    # ── Market context at signal time (frozen snapshot) ────────────────────────
    regime      = db.Column(db.String(20), nullable=True)
    breadth_pct = db.Column(db.Float, nullable=True)
    rvol        = db.Column(db.Float, nullable=True)
    adx         = db.Column(db.Float, nullable=True)
    rsi         = db.Column(db.Float, nullable=True)

    # ── Forward path — filled by comparison_update_job ────────────────────────
    fwd_1d_pct  = db.Column(db.Float, nullable=True)   # (close_+1d / entry) - 1  × 100
    fwd_3d_pct  = db.Column(db.Float, nullable=True)
    fwd_5d_pct  = db.Column(db.Float, nullable=True)
    fwd_10d_pct = db.Column(db.Float, nullable=True)
    mfe_pct     = db.Column(db.Float, nullable=True)   # max favorable excursion %
    mae_pct     = db.Column(db.Float, nullable=True)   # max adverse excursion % (negative)
    days_to_mfe = db.Column(db.Integer, nullable=True)

    # ── Common Evaluation Layer ────────────────────────────────────────────────
    # Same definition for ALL engines: +7% TP, -5% SL, 10-day horizon
    eval_tp_pct   = db.Column(db.Float, default=7.0)   # reference TP used
    eval_sl_pct   = db.Column(db.Float, default=5.0)   # reference SL used (absolute %)
    eval_hit_tp   = db.Column(db.Boolean, nullable=True)   # price hit +7% first
    eval_hit_sl   = db.Column(db.Boolean, nullable=True)   # price hit -5% first
    eval_status   = db.Column(db.String(20), nullable=True) # TP|SL|EXPIRED|OPEN
    eval_pnl_pct  = db.Column(db.Float, nullable=True)     # realized % at exit
    eval_hold_days = db.Column(db.Integer, nullable=True)

    path_updated_at = db.Column(db.DateTime, nullable=True)
    created_at      = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    opportunity = db.relationship("Opportunity", foreign_keys=[opportunity_id])

    @classmethod
    def build_setup_id(cls, signal_date, symbol: str) -> str:
        return f"{signal_date:%Y%m%d}_{symbol}"

    def to_dict(self) -> dict:
        return {
            "setup_id":    self.setup_id,
            "date":        self.signal_date.isoformat() if self.signal_date else None,
            "symbol":      self.symbol,
            "engine":      self.engine,
            "signal_type": self.signal_type,
            "score":       self.score,
            "grade":       self.grade,
            "entry":       self.entry_price,
            "tp1":         self.tp1_price,
            "tp2":         self.tp2_price,
            "sl":          self.sl_price,
            "rr":          self.rr_ratio,
            "regime":      self.regime,
            "breadth_pct": self.breadth_pct,
            "rvol":        self.rvol,
            "adx":         self.adx,
            "rsi":         self.rsi,
            "forward": {
                "fwd_1d":   self.fwd_1d_pct,
                "fwd_3d":   self.fwd_3d_pct,
                "fwd_5d":   self.fwd_5d_pct,
                "fwd_10d":  self.fwd_10d_pct,
                "mfe":      self.mfe_pct,
                "mae":      self.mae_pct,
                "days_to_mfe": self.days_to_mfe,
            },
            "eval": {
                "status":    self.eval_status,
                "hit_tp":    self.eval_hit_tp,
                "hit_sl":    self.eval_hit_sl,
                "pnl_pct":   self.eval_pnl_pct,
                "hold_days": self.eval_hold_days,
            },
        }
