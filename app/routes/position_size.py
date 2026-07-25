"""
Position Size API — /api/position-size

GET /api/position-size?opp_id=123&portfolio=100000

Returns how many shares to buy, position EGP, risk EGP, and a breakdown
of the confidence/regime modifiers applied to the base risk %.

Used by: Telegram bot, admin tools, future mobile app.
Frontend computes client-side using the same logic (no round-trip needed).
"""
import logging
from flask import Blueprint, jsonify, request

from app import db
from app.models.opportunity import Opportunity
from app.models.stock import Stock
from app.services.position_sizing import size_position
from app.services.confidence import compute_confidence

logger = logging.getLogger(__name__)
position_size_bp = Blueprint("position_size", __name__)


@position_size_bp.get("/api/position-size")
def get_position_size():
    """
    Query params:
      opp_id    (int)   — Opportunity ID
      portfolio (float) — Portfolio size in EGP (e.g. 100000)
    """
    opp_id = request.args.get("opp_id", type=int)
    portfolio = request.args.get("portfolio", type=float)

    if not opp_id or not portfolio or portfolio < 1000:
        return jsonify({"error": "يجب تحديد opp_id وحجم محفظة (≥ 1,000 ج.م)"}), 400

    row = (
        db.session.query(Opportunity, Stock)
        .join(Stock, Stock.id == Opportunity.stock_id)
        .filter(Opportunity.id == opp_id)
        .first()
    )

    if not row:
        return jsonify({"error": "الفرصة غير موجودة"}), 404

    opp, stock = row
    snap   = opp.feature_snapshot or {}
    regime = snap.get("regime", "SIDEWAYS") if isinstance(snap, dict) else "SIDEWAYS"

    # Use balanced SL, fall back to fast SL or stored sl_price
    profiles   = snap.get("profiles", {}) if isinstance(snap, dict) else {}
    bal_sl     = profiles.get("BALANCED", {}).get("sl") or profiles.get("FAST", {}).get("sl")
    sl         = bal_sl or opp.sl_price
    tp1        = profiles.get("BALANCED", {}).get("tp") or profiles.get("FAST", {}).get("tp") or opp.tp1_price

    if not opp.entry_price or not sl:
        return jsonify({"error": "بيانات الدخول/وقف الخسارة غير مكتملة"}), 422

    confidence = compute_confidence(opp)

    result = size_position(
        opp_type=opp.opp_type,
        confidence=confidence,
        regime=regime,
        entry=float(opp.entry_price),
        sl=float(sl),
        tp1=float(tp1) if tp1 else None,
        portfolio_egp=portfolio,
    )

    if result is None:
        return jsonify({
            "symbol":   stock.symbol,
            "opp_type": opp.opp_type,
            "message":  "VOL_RADAR لا يُسعَّر — إشارة مراقبة فقط",
            "shares":   0,
        }), 200

    return jsonify({
        "symbol":   stock.symbol,
        "name_ar":  stock.name_ar,
        "opp_id":   opp.id,
        "portfolio": portfolio,
        **result.to_dict(),
    })
