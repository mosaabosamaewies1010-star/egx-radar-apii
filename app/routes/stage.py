"""
Stage Breakout API — /api/stage-breakout
Returns today's STAGE_STRONG / STAGE_DEVELOPING signals from the DB.
Sorted by stage_score DESC (best quality first).
"""
import logging
from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import desc

from app import db
from app.models.opportunity import Opportunity
from app.models.stock import Stock
from app.services.confidence import compute_confidence
from app.services.explain_3tier import explain_signal

logger = logging.getLogger(__name__)
stage_bp = Blueprint("stage", __name__)


@stage_bp.get("/api/stage-breakout")
def get_stage_breakouts():
    """
    GET /api/stage-breakout
    Query params:
      sharia=1  — شريعة فقط
      limit=N   — max results (default 50)
    """
    sharia_only = request.args.get("sharia", "0") == "1"
    limit       = min(int(request.args.get("limit", 50)), 200)

    q = (
        db.session.query(Opportunity, Stock)
        .join(Stock, Stock.id == Opportunity.stock_id)
        .filter(
            Stock.is_active == True,
            Opportunity.opp_type.like("STAGE_%"),
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

    # Sort by stage_score DESC (field lives inside feature_snapshot JSON)
    def _score(pair):
        opp, _ = pair
        snap = opp.feature_snapshot or {}
        return snap.get("stage_score", 0) if isinstance(snap, dict) else 0

    latest.sort(key=_score, reverse=True)

    items = []
    for opp, stock in latest:
        snap = opp.feature_snapshot or {}
        if not isinstance(snap, dict):
            snap = {}

        profiles = snap.get("profiles", {})
        fast_p   = profiles.get("FAST", {})
        bal_p    = profiles.get("BALANCED", {})

        items.append({
            "id":           opp.id,
            "symbol":       stock.symbol,
            "name_ar":      stock.name_ar,
            "is_sharia":    stock.is_sharia,
            "run_date":     opp.run_date.isoformat() if opp.run_date else None,
            "opp_type":     opp.opp_type,
            "strength":     snap.get("strength", opp.opp_type.replace("STAGE_", "")),
            "stage_score":  snap.get("stage_score", 0),
            "entry_price":  opp.entry_price,
            "fast_tp":      fast_p.get("tp",  opp.tp1_price),
            "fast_sl":      fast_p.get("sl",  opp.sl_price),
            "balanced_tp":  bal_p.get("tp",   opp.tp2_price),
            "balanced_sl":  bal_p.get("sl",   opp.sl_price),
            "rr_ratio":     opp.rr_ratio,
            "adx":          snap.get("adx", 0),
            "rsi":          snap.get("rsi", 0),
            "vol_age_bars": snap.get("vol_age_bars", 0),
            "vol_rvol":     snap.get("vol_rvol", 0),
            "vol_date":     snap.get("vol_date", ""),
            "adt":          snap.get("adt", 0),
            "reasons":      snap.get("reasons", []),
            "last_price":   stock.last_price,
            "last_change_pct": stock.last_change_pct,
            "confidence":   compute_confidence(opp),
            "regime":       snap.get("regime", "SIDEWAYS"),
            "breadth_pct":  snap.get("breadth_pct", None),
            "explain":      explain_signal(opp),
        })

    return jsonify({
        "total":      len(items),
        "items":      items,
    })
