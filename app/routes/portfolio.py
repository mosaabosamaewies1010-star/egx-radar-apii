"""
/api/portfolio — Portfolio Holdings CRUD
User-id scoped (optional JWT — null user_id for anonymous sessions).
"""
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, abort
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from app import db
from app.models.stock import Stock
from app.models.portfolio import PortfolioHolding
from app.models.score import RadarScoreHistory
from app.utils.pro_guard import require_pro
from app.services.portfolio_health import compute_portfolio_health

portfolio_bp = Blueprint("portfolio", __name__)


def _get_user_id():
    """Return int user_id from JWT if present, else None."""
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        return int(identity) if identity else None
    except Exception:
        return None


def _enrich(h: PortfolioHolding) -> dict:
    """Serialize holding + add live unrealized P&L from Stock.last_price."""
    d = h.to_dict()
    if h.is_open and h.stock and h.stock.last_price:
        price = h.stock.last_price
        unreal     = round((price - h.avg_cost) * h.quantity, 2)
        unreal_pct = round((price - h.avg_cost) / h.avg_cost * 100, 2)
        d["current_price"]      = price
        d["unrealized_pnl"]     = unreal
        d["unrealized_pnl_pct"] = unreal_pct
    else:
        d["current_price"]      = None
        d["unrealized_pnl"]     = None
        d["unrealized_pnl_pct"] = None
    return d


@portfolio_bp.get("/api/portfolio")
def list_holdings():
    err = require_pro()
    if err:
        return err
    user_id  = _get_user_id()
    holdings = (
        PortfolioHolding.query
        .filter_by(user_id=user_id)
        .order_by(PortfolioHolding.opened_at.desc())
        .all()
    )

    open_h   = [h for h in holdings if h.is_open]
    closed_h = [h for h in holdings if not h.is_open]

    total_invested = round(sum(h.cost_basis for h in open_h), 2)
    total_realized = round(
        sum(h.realized_pnl for h in closed_h if h.realized_pnl is not None), 2
    )

    unreal_vals = []
    for h in open_h:
        if h.stock and h.stock.last_price:
            unreal_vals.append((h.stock.last_price - h.avg_cost) * h.quantity)
    total_unrealized = round(sum(unreal_vals), 2) if unreal_vals else None

    return jsonify({
        "summary": {
            "total_invested":      total_invested,
            "open_positions":      len(open_h),
            "closed_positions":    len(closed_h),
            "total_realized_pnl":  total_realized,
            "total_unrealized_pnl": total_unrealized,
        },
        "holdings": [_enrich(h) for h in holdings],
    })


@portfolio_bp.get("/api/portfolio/health")
def portfolio_health():
    """
    Portfolio Health — التنويع + المخاطرة + الجودة الفنية + الأداء.
    منطق موافَق عليه (انظر app/services/portfolio_health.py للتفاصيل والمنهجية).
    """
    err = require_pro()
    if err:
        return err

    user_id = _get_user_id()
    open_holdings = (
        PortfolioHolding.query
        .filter_by(user_id=user_id, closed_at=None)
        .all()
    )
    closed_holdings = (
        PortfolioHolding.query
        .filter(PortfolioHolding.user_id == user_id, PortfolioHolding.closed_at.isnot(None))
        .all()
    )

    total_invested = sum(h.cost_basis for h in open_holdings)
    total_unrealized = None
    unreal_vals = []
    for h in open_holdings:
        if h.stock and h.stock.last_price:
            unreal_vals.append((h.stock.last_price - h.avg_cost) * h.quantity)
    if unreal_vals:
        total_unrealized = sum(unreal_vals)
    total_realized = sum(h.realized_pnl for h in closed_holdings if h.realized_pnl is not None)

    # أحدث radar_score/atr_pct لكل سهم في المحفظة المفتوحة (استعلام واحد لكل الأسهم)
    stock_ids = [h.stock_id for h in open_holdings]
    latest_scores: dict[int, dict] = {}
    if stock_ids:
        rows = (
            RadarScoreHistory.query
            .filter(RadarScoreHistory.stock_id.in_(stock_ids))
            .order_by(RadarScoreHistory.stock_id, RadarScoreHistory.run_date.desc())
            .all()
        )
        for r in rows:
            if r.stock_id not in latest_scores:   # أول ظهور = الأحدث (مرتّب تنازليًا)
                latest_scores[r.stock_id] = {"score": r.score, "atr_pct": r.atr_pct}

    result = compute_portfolio_health(
        open_holdings=open_holdings,
        total_invested=total_invested,
        total_unrealized_pnl=total_unrealized,
        total_realized_pnl=total_realized,
        latest_scores=latest_scores,
    )

    return jsonify({
        "health_score":    result.health_score,
        "components":      result.components,
        "warnings":        result.warnings,
        "recommendations": result.recommendations,
        "positions":       result.positions,
        "message":         result.message,
    })


@portfolio_bp.post("/api/portfolio")
def add_holding():
    user_id  = _get_user_id()
    data     = request.get_json(silent=True) or {}

    symbol   = (data.get("symbol") or "").strip().upper()
    quantity = data.get("quantity")
    avg_cost = data.get("avg_cost")
    notes    = (data.get("notes") or "").strip() or None

    if not symbol:
        return jsonify({"error": "رمز السهم مطلوب"}), 422
    if quantity is None or float(quantity) <= 0:
        return jsonify({"error": "الكمية يجب أن تكون أكبر من صفر"}), 422
    if avg_cost is None or float(avg_cost) <= 0:
        return jsonify({"error": "سعر الشراء يجب أن يكون أكبر من صفر"}), 422

    stock = Stock.query.filter_by(symbol=symbol).first()
    if not stock:
        return jsonify({"error": f"السهم '{symbol}' غير موجود في قاعدة البيانات"}), 404

    h = PortfolioHolding(
        user_id=user_id,
        stock_id=stock.id,
        quantity=float(quantity),
        avg_cost=float(avg_cost),
        notes=notes,
    )
    db.session.add(h)
    db.session.commit()
    return jsonify(_enrich(h)), 201


@portfolio_bp.patch("/api/portfolio/<int:holding_id>/close")
def close_holding(holding_id: int):
    user_id = _get_user_id()
    h       = db.session.get(PortfolioHolding, holding_id)

    if not h or h.user_id != user_id:
        abort(404)
    if not h.is_open:
        return jsonify({"error": "الصفقة مغلقة بالفعل"}), 409

    data        = request.get_json(silent=True) or {}
    close_price = data.get("close_price")

    if close_price is None or float(close_price) <= 0:
        return jsonify({"error": "سعر الإغلاق يجب أن يكون أكبر من صفر"}), 422

    h.close_price = float(close_price)
    h.closed_at   = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(_enrich(h))


@portfolio_bp.delete("/api/portfolio/<int:holding_id>")
def delete_holding(holding_id: int):
    user_id = _get_user_id()
    h       = db.session.get(PortfolioHolding, holding_id)

    if not h or h.user_id != user_id:
        abort(404)

    db.session.delete(h)
    db.session.commit()
    return "", 204
