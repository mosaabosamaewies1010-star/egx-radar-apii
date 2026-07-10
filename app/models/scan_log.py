from datetime import datetime, timezone
from app import db


class ScanLog(db.Model):
    """
    One row per daily pipeline run.
    Records which versions ran, counts, and duration for audit + release notes.
    """
    __tablename__ = "scan_logs"

    id               = db.Column(db.Integer, primary_key=True)
    run_date         = db.Column(db.Date, nullable=False, index=True)
    started_at       = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at      = db.Column(db.DateTime, nullable=True)

    # Version registry
    sra_version      = db.Column(db.String(20), default="SRA_v1.0")
    scanner_version  = db.Column(db.String(20), default="Scanner_v1.0")
    kb_version       = db.Column(db.String(20), default="KB_v1.0")

    # Counts
    stocks_scanned   = db.Column(db.Integer, default=0)
    sra_signals      = db.Column(db.Integer, default=0)
    momentum_signals = db.Column(db.Integer, default=0)
    outcomes_closed  = db.Column(db.Integer, default=0)
    kb_size          = db.Column(db.Integer, default=0)

    # Regime snapshot
    regime           = db.Column(db.String(20), nullable=True)
    breadth_pct      = db.Column(db.Float, nullable=True)

    # Status
    status           = db.Column(db.String(20), default="running")  # running | success | partial | failed
    error_message    = db.Column(db.Text, nullable=True)

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return round((self.finished_at - self.started_at).total_seconds())
        return None

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "run_date":         self.run_date.isoformat() if self.run_date else None,
            "started_at":       self.started_at.isoformat() if self.started_at else None,
            "duration_seconds": self.duration_seconds,
            "sra_version":      self.sra_version,
            "scanner_version":  self.scanner_version,
            "kb_version":       self.kb_version,
            "stocks_scanned":   self.stocks_scanned,
            "sra_signals":      self.sra_signals,
            "momentum_signals": self.momentum_signals,
            "outcomes_closed":  self.outcomes_closed,
            "kb_size":          self.kb_size,
            "regime":           self.regime,
            "breadth_pct":      self.breadth_pct,
            "status":           self.status,
            "error_message":    self.error_message,
        }
