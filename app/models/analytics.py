from datetime import datetime, timezone
from app import db


class AnalyticsEvent(db.Model):
    __tablename__ = "analytics_events"

    id         = db.Column(db.Integer,  primary_key=True)
    name       = db.Column(db.String(80), nullable=False, index=True)
    props      = db.Column(db.JSON,       nullable=True)
    ts         = db.Column(db.BigInteger, nullable=True)   # client epoch ms
    received_at= db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Optional denormalized columns for fast queries
    symbol     = db.Column(db.String(20), nullable=True, index=True)
    path       = db.Column(db.String(255), nullable=True)
    widget_id  = db.Column(db.String(30),  nullable=True, index=True)
