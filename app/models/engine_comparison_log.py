"""
Engine Comparison Log — canonical record for Engine Comparison v1.

One row per (signal_date, symbol, engine). Written by daily_scan.py immediately
after each engine flushes its Opportunity. Forward-path fields are filled later
by comparison_update_job (runs at 16:05 Cairo after markets close).

Key design decisions
--------------------
reference_price
    Always df["close"].iloc[-1] at scan time — the price a trader would see
    right after market close. Used for ALL forward-return calculations so that
    every engine is evaluated from the same reference point.

    SRA native entry_price is close[sl_idx] * 1.002 (historical swing-low
    price). It is stored for information but NEVER used in forward-return or
    eval calculations — reference_price is used instead.

Common Evaluation Layer
    Same binary test for ALL engines:
        COMMON_TP = +7.0%  from reference_price → eval_status = "TP"
        COMMON_SL = -5.0%  from reference_price → eval_status = "SL"
        COMMON_MAX_HOLD = 10 trading sessions
    eval_status stays "EXPIRED" if neither threshold is reached in 10 days —
    the status NEVER converts to WIN/LOSS.  Instead, expiry_pnl_pct records
    the actual mark-to-market return at day 10.

Two independent performance lenses
    1. Common Target Test  — eval_status (TP | SL | EXPIRED), eval_pnl_pct
    2. 10-Day MTM Return   — fwd_10d_pct and expiry_pnl_pct (from reference)

Duplicate guard
    UniqueConstraint on (signal_date, symbol, engine) prevents double-writes
    if the scan trigger fires twice in the same day.
"""
from datetime import datetime, timezone
from app import db


class EngineComparisonLog(db.Model):
    __tablename__ = "engine_comparison_logs"
    __table_args__ = (
        db.UniqueConstraint(
            "signal_date", "symbol", "engine",
            name="uq_cmp_log_date_sym_engine",
        ),
    )

    id          = db.Column(db.Integer, primary_key=True)
    setup_id    = db.Column(db.String(32), nullable=False, index=True)   # YYYYMMDD_SYMBOL
    signal_date = db.Column(db.Date, nullable=False, index=True)
    symbol      = db.Column(db.String(20), nullable=False, index=True)
    engine      = db.Column(db.String(20), nullable=False)               # STAGE|TREND|VOL_RADAR|SRA
    signal_type = db.Column(db.String(40), nullable=True)                # STAGE_STRONG, SRA_A+, …

    opportunity_id = db.Column(
        db.Integer, db.ForeignKey("opportunities.id"), nullable=True, index=True
    )

    # ── Engine native levels (kept verbatim from each engine) ─────────────────
    entry_price   = db.Column(db.Float, nullable=True)   # engine-native entry (SRA may differ)
    tp1_price     = db.Column(db.Float, nullable=True)
    tp2_price     = db.Column(db.Float, nullable=True)
    sl_price      = db.Column(db.Float, nullable=True)
    rr_ratio      = db.Column(db.Float, nullable=True)
    max_hold_days = db.Column(db.Integer, nullable=True)

    # ── Canonical reference for all forward-return / eval calculations ────────
    # Always df["close"].iloc[-1] at scan time for EVERY engine.
    # For STAGE/TREND/VOL_RADAR this equals entry_price.
    # For SRA this differs from entry_price (which is swing-low based).
    reference_price = db.Column(db.Float, nullable=True)

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
    # Returns are (close_+Nd / reference_price - 1) × 100
    fwd_1d_pct  = db.Column(db.Float, nullable=True)
    fwd_3d_pct  = db.Column(db.Float, nullable=True)
    fwd_5d_pct  = db.Column(db.Float, nullable=True)
    fwd_10d_pct = db.Column(db.Float, nullable=True)
    mfe_pct     = db.Column(db.Float, nullable=True)   # max favorable excursion %
    mae_pct     = db.Column(db.Float, nullable=True)   # max adverse excursion % (negative)
    days_to_mfe = db.Column(db.Integer, nullable=True)

    # ── Common Evaluation Layer ────────────────────────────────────────────────
    # Thresholds recorded explicitly so future analysis always knows the rule used
    eval_tp_pct    = db.Column(db.Float, default=7.0)   # TP threshold %
    eval_sl_pct    = db.Column(db.Float, default=5.0)   # SL threshold % (stored positive)
    eval_hit_tp    = db.Column(db.Boolean, nullable=True)
    eval_hit_sl    = db.Column(db.Boolean, nullable=True)
    eval_status    = db.Column(db.String(20), nullable=True)  # TP|SL|EXPIRED|OPEN

    # eval_exit_price — the price at which the evaluation rule concluded:
    #   TP      → reference_price × 1.07   (the threshold the intraday high crossed)
    #   SL      → reference_price × 0.95   (the threshold the intraday low crossed)
    #   EXPIRED → close of the 10th trading session
    eval_exit_price = db.Column(db.Float, nullable=True)

    # eval_pnl_pct always derived as (eval_exit_price / reference_price - 1) × 100:
    #   TP → exactly +7.0; SL → exactly -5.0; EXPIRED → actual close return
    eval_pnl_pct   = db.Column(db.Float, nullable=True)
    eval_hold_days = db.Column(db.Integer, nullable=True)
    eval_exit_date = db.Column(db.Date, nullable=True)        # calendar date of exit

    # ── Expiry mark-to-market (close of the exit session) ─────────────────────
    # For TP/SL:   close of the session where the threshold was first breached
    # For EXPIRED: close of the 10th trading session
    # expiry_pnl_pct = (expiry_close / reference_price - 1) × 100
    # Differs from eval_pnl_pct for TP/SL — provides actual close return
    # alongside the threshold-based eval_pnl_pct for richer analysis.
    expiry_close   = db.Column(db.Float, nullable=True)
    expiry_pnl_pct = db.Column(db.Float, nullable=True)

    path_updated_at = db.Column(db.DateTime, nullable=True)
    created_at      = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    opportunity = db.relationship("Opportunity", foreign_keys=[opportunity_id])

    @classmethod
    def build_setup_id(cls, signal_date, symbol: str) -> str:
        return f"{signal_date:%Y%m%d}_{symbol}"

    def to_dict(self) -> dict:
        return {
            "setup_id":        self.setup_id,
            "date":            self.signal_date.isoformat() if self.signal_date else None,
            "symbol":          self.symbol,
            "engine":          self.engine,
            "signal_type":     self.signal_type,
            "score":           self.score,
            "grade":           self.grade,
            "entry_native":    self.entry_price,
            "reference_price": self.reference_price,
            "tp1":             self.tp1_price,
            "tp2":             self.tp2_price,
            "sl":              self.sl_price,
            "rr":              self.rr_ratio,
            "regime":          self.regime,
            "breadth_pct":     self.breadth_pct,
            "rvol":            self.rvol,
            "adx":             self.adx,
            "rsi":             self.rsi,
            "forward": {
                "fwd_1d":      self.fwd_1d_pct,
                "fwd_3d":      self.fwd_3d_pct,
                "fwd_5d":      self.fwd_5d_pct,
                "fwd_10d":     self.fwd_10d_pct,
                "mfe":         self.mfe_pct,
                "mae":         self.mae_pct,
                "days_to_mfe": self.days_to_mfe,
            },
            "eval": {
                "status":      self.eval_status,
                "tp_pct":      self.eval_tp_pct,
                "sl_pct":      self.eval_sl_pct,
                "hit_tp":      self.eval_hit_tp,
                "hit_sl":      self.eval_hit_sl,
                "exit_price":  self.eval_exit_price,
                "pnl_pct":     self.eval_pnl_pct,
                "hold_days":   self.eval_hold_days,
                "exit_date":   self.eval_exit_date.isoformat() if self.eval_exit_date else None,
            },
            "expiry": {
                "close":   self.expiry_close,
                "pnl_pct": self.expiry_pnl_pct,
            },
        }
