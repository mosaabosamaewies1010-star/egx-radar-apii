"""
Volume Radar API — /api/volume-radar
Returns active VOL_RADAR watch signals from the DB.
Sorted by vol_age_bars ASC (newest VOL event first = most likely to cross soon).
"""
import logging
from flask import Blueprint, jsonify, request
from sqlalchemy import desc

from app import db
from app.models.opportunity import Opportunity
from app.models.stock import Stock
from app.services.confidence import compute_confidence
from app.services.explain_3tier import explain_signal

logger = logging.getLogger(__name__)
vol_radar_bp = Blueprint("vol_radar", __name__)


@vol_radar_bp.get("/api/volume-radar")
def get_volume_radar():
    """
    GET /api/volume-radar
    Query params:
      sharia=1  — شريعة فقط
      limit=N   — max results (default 100)
    """
    sharia_only = request.args.get("sharia", "0") == "1"
    limit       = min(int(request.args.get("limit", 100)), 300)

    q = (
        db.session.query(Opportunity, Stock)
        .join(Stock, Stock.id == Opportunity.stock_id)
        .filter(
            Stock.is_active == True,
            Opportunity.opp_type == "VOL_RADAR",
            Opportunity.outcome == "PENDING",
        )
    )

    if sharia_only:
        q = q.filter(Stock.is_sharia == True)

    rows = q.order_by(desc(Opportunity.run_date)).limit(limit * 3).all()

    # De-duplicate: one entry per stock, most recent date wins
    seen   = {}
    latest = []
    for opp, stock in rows:
        if stock.symbol not in seen:
            seen[stock.symbol] = True
            latest.append((opp, stock))
        if len(latest) >= limit:
            break

    # Sort: newest VOL event (smallest age) first → most likely close to cross
    def _age(pair):
        opp, _ = pair
        snap = opp.feature_snapshot or {}
        return snap.get("vol_age_bars", 999) if isinstance(snap, dict) else 999

    latest.sort(key=_age)

    items = []
    for opp, stock in latest:
        snap = opp.feature_snapshot or {}
        if not isinstance(snap, dict):
            snap = {}

        items.append({
            "id":             opp.id,
            "symbol":         stock.symbol,
            "name_ar":        stock.name_ar,
            "is_sharia":      stock.is_sharia,
            "run_date":       opp.run_date.isoformat() if opp.run_date else None,
            "opp_type":       "VOL_RADAR",
            "vol_age_bars":   snap.get("vol_age_bars", 0),
            "vol_rvol":       snap.get("vol_rvol", 0),
            "vol_date":       snap.get("vol_date", ""),
            "ema_gap_pct":    snap.get("ema_gap_pct", 0),
            "ema_fast":       snap.get("ema_fast", 0),
            "ema_slow":       snap.get("ema_slow", 0),
            "adt":            snap.get("adt", 0),
            "close":          snap.get("close", opp.entry_price),
            "watch_reasons":  snap.get("watch_reasons", []),
            "last_price":     stock.last_price,
            "last_change_pct": stock.last_change_pct,
            "confidence":     compute_confidence(opp),
            "regime":         snap.get("regime", "SIDEWAYS"),
            "breadth_pct":    snap.get("breadth_pct", None),
            "explain":        explain_signal(opp),
        })

    return jsonify({
        "total": len(items),
        "items": items,
    })
