"""
/api/watchlist — Watchlist CRUD
User-id scoped (optional JWT — null user_id for anonymous sessions).
"""
from flask import Blueprint, jsonify, request, abort
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from app import db
from app.models.stock import Stock
from app.models.watchlist import Watchlist
from app.utils.pro_guard import current_is_pro, FREE_MAX_WATCHLIST

watchlist_bp = Blueprint("watchlist", __name__)


def _get_user_id():
    """Return int user_id from JWT if present, else None."""
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        return int(identity) if identity else None
    except Exception:
        return None


def _enrich(w: Watchlist) -> dict:
    """Serialize watchlist entry + attach latest price snapshot from Stock."""
    d = w.to_dict()
    if w.stock:
        d["last_price"]      = w.stock.last_price
        d["last_change_pct"] = w.stock.last_change_pct
        d["sector"]          = w.stock.sector
        d["is_sharia"]       = w.stock.is_sharia
    else:
        d["last_price"]      = None
        d["last_change_pct"] = None
        d["sector"]          = None
        d["is_sharia"]       = False
    return d


# ── GET /api/watchlist ────────────────────────────────────────────────────────

@watchlist_bp.get("/api/watchlist")
def list_watchlist():
    user_id = _get_user_id()
    items = (
        Watchlist.query
        .filter_by(user_id=user_id)
        .order_by(Watchlist.created_at.desc())
        .all()
    )
    return jsonify({"items": [_enrich(w) for w in items], "count": len(items)})


# ── POST /api/watchlist ───────────────────────────────────────────────────────

@watchlist_bp.post("/api/watchlist")
def add_to_watchlist():
    user_id = _get_user_id()
    data    = request.get_json(silent=True) or {}

    symbol = (data.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "رمز السهم مطلوب"}), 422

    stock = Stock.query.filter_by(symbol=symbol).first()
    if not stock:
        return jsonify({"error": f"السهم '{symbol}' غير موجود في قاعدة البيانات"}), 404

    # Duplicate guard — one entry per (user_id, stock_id)
    existing = Watchlist.query.filter_by(user_id=user_id, stock_id=stock.id).first()
    if existing:
        return jsonify({"error": "السهم موجود بالفعل في قائمة المتابعة"}), 409

    # Free tier: max 5 watchlist items
    if not current_is_pro():
        count = Watchlist.query.filter_by(user_id=user_id).count()
        if count >= FREE_MAX_WATCHLIST:
            return jsonify({
                "error": f"المستخدم المجاني يمكنه متابعة {FREE_MAX_WATCHLIST} أسهم فقط — اشترك في PRO للمزيد",
                "pro_required": True,
                "upgrade_url": "/payments",
            }), 403

    notes             = (data.get("notes") or "").strip() or None
    alert_price_above = data.get("alert_price_above")
    alert_price_below = data.get("alert_price_below")

    if alert_price_above is not None and float(alert_price_above) <= 0:
        return jsonify({"error": "سعر التنبيه يجب أن يكون أكبر من صفر"}), 422
    if alert_price_below is not None and float(alert_price_below) <= 0:
        return jsonify({"error": "سعر التنبيه يجب أن يكون أكبر من صفر"}), 422

    w = Watchlist(
        user_id=user_id,
        stock_id=stock.id,
        notes=notes,
        alert_price_above=float(alert_price_above) if alert_price_above is not None else None,
        alert_price_below=float(alert_price_below) if alert_price_below is not None else None,
    )
    db.session.add(w)
    db.session.commit()
    return jsonify(_enrich(w)), 201


# ── PATCH /api/watchlist/<id> ─────────────────────────────────────────────────

@watchlist_bp.patch("/api/watchlist/<int:item_id>")
def update_watchlist_item(item_id: int):
    user_id = _get_user_id()
    w = db.session.get(Watchlist, item_id)

    if not w or w.user_id != user_id:
        abort(404)

    data = request.get_json(silent=True) or {}

    if "notes" in data:
        w.notes = (data["notes"] or "").strip() or None

    if "alert_price_above" in data:
        val = data["alert_price_above"]
        if val is not None and float(val) <= 0:
            return jsonify({"error": "سعر التنبيه يجب أن يكون أكبر من صفر"}), 422
        w.alert_price_above = float(val) if val is not None else None

    if "alert_price_below" in data:
        val = data["alert_price_below"]
        if val is not None and float(val) <= 0:
            return jsonify({"error": "سعر التنبيه يجب أن يكون أكبر من صفر"}), 422
        w.alert_price_below = float(val) if val is not None else None

    db.session.commit()
    return jsonify(_enrich(w))


# ── DELETE /api/watchlist/<id> ────────────────────────────────────────────────

@watchlist_bp.delete("/api/watchlist/<int:item_id>")
def remove_from_watchlist(item_id: int):
    user_id = _get_user_id()
    w = db.session.get(Watchlist, item_id)

    if not w or w.user_id != user_id:
        abort(404)

    db.session.delete(w)
    db.session.commit()
    return "", 204
