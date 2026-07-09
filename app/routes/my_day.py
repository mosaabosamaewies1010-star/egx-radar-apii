"""
GET /api/my-day — personalised daily summary (no cache — user-specific)
"""
from datetime import date
from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from sqlalchemy import func

from app import db
from app.models.portfolio import PortfolioHolding
from app.models.watchlist import Watchlist
from app.models.notification import Notification
from app.models.opportunity import Opportunity
from app.models.score import RadarScoreHistory

my_day_bp = Blueprint("my_day", __name__)


def _get_user_id():
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        return int(identity) if identity else None
    except Exception:
        return None


@my_day_bp.get("/api/my-day")
def my_day():
    user_id        = _get_user_id()
    is_authenticated = user_id is not None

    # ── Portfolio snapshot ─────────────────────────────────────────────────────
    open_holdings = (
        PortfolioHolding.query
        .filter_by(user_id=user_id)
        .filter(PortfolioHolding.closed_at.is_(None))
        .all()
    )
    portfolio = None
    if open_holdings:
        total_invested  = sum(h.cost_basis for h in open_holdings)
        unrealized_list = []
        for h in open_holdings:
            if h.stock and h.stock.last_price:
                unrealized_list.append((h.stock.last_price - h.avg_cost) * h.quantity)

        unrealized_pnl     = round(sum(unrealized_list), 2) if unrealized_list else None
        unrealized_pnl_pct = (
            round(unrealized_pnl / total_invested * 100, 2)
            if unrealized_pnl is not None and total_invested > 0
            else None
        )
        portfolio = {
            "open_positions":    len(open_holdings),
            "total_invested":    round(total_invested, 2),
            "unrealized_pnl":    unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
        }

    # ── Watchlist ──────────────────────────────────────────────────────────────
    watchlist = (
        Watchlist.query
        .filter_by(user_id=user_id)
        .all()
    )
    watchlist_count = len(watchlist)

    watchlist_alerts = []
    for w in watchlist:
        if not w.stock or w.stock.last_price is None:
            continue
        price = w.stock.last_price
        if w.alert_price_above and price > w.alert_price_above:
            watchlist_alerts.append({
                "symbol":       w.stock.symbol,
                "name_ar":      w.stock.name_ar,
                "alert_type":   "above",
                "current_price": price,
                "alert_price":  w.alert_price_above,
            })
        elif w.alert_price_below and price < w.alert_price_below:
            watchlist_alerts.append({
                "symbol":       w.stock.symbol,
                "name_ar":      w.stock.name_ar,
                "alert_type":   "below",
                "current_price": price,
                "alert_price":  w.alert_price_below,
            })

    # ── Unread notifications ───────────────────────────────────────────────────
    unread_notifications = (
        Notification.query
        .filter_by(user_id=user_id, is_read=False)
        .count()
    )

    # ── Active opportunities for watchlisted stocks ───────────────────────────
    watchlist_stock_ids = [w.stock_id for w in watchlist]
    active_opportunities = []
    if watchlist_stock_ids:
        opps = (
            db.session.query(Opportunity)
            .filter(
                Opportunity.stock_id.in_(watchlist_stock_ids),
                Opportunity.outcome == "PENDING",
                Opportunity.is_active == True,
            )
            .order_by(Opportunity.radar_score.desc())
            .limit(5)
            .all()
        )
        active_opportunities = [
            {
                "symbol":      opp.stock.symbol if opp.stock else None,
                "name_ar":     opp.stock.name_ar if opp.stock else None,
                "opp_type":    opp.opp_type,
                "radar_score": opp.radar_score,
                "run_date":    opp.run_date.isoformat(),
            }
            for opp in opps
        ]

    # ── Latest score date ─────────────────────────────────────────────────────
    latest_date = db.session.query(func.max(RadarScoreHistory.run_date)).scalar()

    return jsonify({
        "as_of":                     latest_date.isoformat() if latest_date else date.today().isoformat(),
        "is_authenticated":          is_authenticated,
        "portfolio":                 portfolio,
        "watchlist_count":           watchlist_count,
        "watchlist_alerts":          watchlist_alerts,
        "unread_notifications":      unread_notifications,
        "active_opportunities":      active_opportunities,
    })
