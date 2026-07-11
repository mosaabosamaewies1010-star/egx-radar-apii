"""
Admin-only endpoints — all protected by BOT_API_KEY header or query param.

GET  /api/admin/health        — system health (public, for frontend dashboard)
GET  /api/admin/users         — list all registered users
POST /api/admin/grant-pro     — set is_pro=True for a given email
POST /api/admin/revoke-pro    — set is_pro=False for a given email
GET  /api/admin/analytics     — aggregated event counts / page views
"""
import os
from datetime import date, timedelta, datetime, timezone
from flask import Blueprint, jsonify, request
from sqlalchemy import func

from app import db
from app.models.user import User
from app.models.analytics import AnalyticsEvent

admin_bp = Blueprint("admin", __name__)


def _check_key():
    """Return 401 if BOT_API_KEY missing or wrong."""
    api_key  = request.headers.get("X-API-Key") or request.args.get("api_key")
    expected = os.getenv("BOT_API_KEY")
    if not expected or api_key != expected:
        return jsonify({"error": "unauthorized"}), 401
    return None


# ── Health (public — used by frontend admin dashboard) ────────────────────────

@admin_bp.get("/api/admin/health")
def system_health():
    from app.models.opportunity import Opportunity
    from app.models.score       import RadarScoreHistory
    from app.models.regime      import MarketRegimeHistory

    today     = date.today()
    week_ago  = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    signals_today = Opportunity.query.filter_by(run_date=today).count()
    open_trades   = Opportunity.query.filter_by(outcome="PENDING", is_active=True).count()

    sra_open = (
        Opportunity.query
        .filter(
            Opportunity.opp_type.like("SRA_%"),
            Opportunity.outcome == "PENDING",
            Opportunity.is_active == True,
        ).all()
    )

    grade_dist = {"A+": 0, "A": 0, "B": 0}
    sra_scores = []
    for o in sra_open:
        snap = o.feature_snapshot or {}
        g    = snap.get("sra_grade", "B")
        grade_dist[g] = grade_dist.get(g, 0) + 1
        sc = snap.get("sra_score")
        if sc is not None:
            sra_scores.append(float(sc))

    avg_sra_score = round(sum(sra_scores) / len(sra_scores), 1) if sra_scores else None

    closed      = Opportunity.query.filter(Opportunity.outcome.in_(["WIN", "LOSS", "EXPIRED"])).all()
    total_closed = len(closed)
    wins         = sum(1 for o in closed if o.outcome == "WIN")
    losses       = sum(1 for o in closed if o.outcome == "LOSS")
    win_rate     = round(wins / total_closed * 100, 1) if total_closed > 0 else None

    kb_size = (
        Opportunity.query
        .filter(Opportunity.opp_type.like("SRA_%"), Opportunity.outcome.in_(["WIN", "LOSS"]))
        .count()
    )

    scored_today = RadarScoreHistory.query.filter_by(run_date=today).count()
    scored_week  = (
        db.session.query(func.count(func.distinct(RadarScoreHistory.run_date)))
        .filter(RadarScoreHistory.run_date >= week_ago)
        .scalar() or 0
    )

    regime_rec  = MarketRegimeHistory.query.order_by(MarketRegimeHistory.run_date.desc()).first()
    regime_info = {
        "regime":     regime_rec.regime     if regime_rec else None,
        "confidence": regime_rec.confidence if regime_rec else None,
        "run_date":   regime_rec.run_date.isoformat() if regime_rec else None,
    } if regime_rec else None

    total_users = User.query.count()
    pro_users   = User.query.filter_by(is_pro=True).count()

    return jsonify({
        "as_of": today.isoformat(),
        "users": {
            "total": total_users,
            "pro":   pro_users,
            "free":  total_users - pro_users,
        },
        "signals": {
            "today":    signals_today,
            "sra_open": len(sra_open),
            "all_open": open_trades,
        },
        "performance": {
            "total_closed": total_closed,
            "wins":         wins,
            "losses":       losses,
            "win_rate":     win_rate,
        },
        "sra": {
            "avg_score":  avg_sra_score,
            "grade_dist": grade_dist,
        },
        "knowledge_base": {
            "size": kb_size,
        },
        "scanner": {
            "scored_today": scored_today,
            "scan_days_7d": scored_week,
        },
        "regime": regime_info,
    })


# ── Users list ────────────────────────────────────────────────────────────────

@admin_bp.get("/api/admin/users")
def list_users():
    err = _check_key()
    if err:
        return err

    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify({
        "count": len(users),
        "users": [
            {
                "id":         u.id,
                "email":      u.email,
                "name":       u.name,
                "is_pro":     u.is_pro,
                "is_active":  u.is_active,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login": u.last_login_at.isoformat() if u.last_login_at else None,
            }
            for u in users
        ],
    })


# ── Grant / revoke PRO ────────────────────────────────────────────────────────

@admin_bp.post("/api/admin/grant-pro")
def grant_pro():
    err = _check_key()
    if err:
        return err

    body  = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "email required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": f"user not found: {email}"}), 404

    user.is_pro = True
    db.session.commit()
    return jsonify({"ok": True, "email": user.email, "is_pro": True})


@admin_bp.post("/api/admin/revoke-pro")
def revoke_pro():
    err = _check_key()
    if err:
        return err

    body  = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "email required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": f"user not found: {email}"}), 404

    user.is_pro = False
    db.session.commit()
    return jsonify({"ok": True, "email": user.email, "is_pro": False})


# ── Analytics summary ─────────────────────────────────────────────────────────

@admin_bp.get("/api/admin/analytics")
def analytics_summary():
    err = _check_key()
    if err:
        return err

    days = int(request.args.get("days", 7))
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)

    total_events = AnalyticsEvent.query.filter(AnalyticsEvent.received_at >= since_dt).count()

    page_views = (
        AnalyticsEvent.query
        .filter(
            AnalyticsEvent.name == "page_view",
            AnalyticsEvent.received_at >= since_dt,
        )
        .count()
    )

    event_breakdown = (
        db.session.query(AnalyticsEvent.name, func.count(AnalyticsEvent.id))
        .filter(AnalyticsEvent.received_at >= since_dt)
        .group_by(AnalyticsEvent.name)
        .order_by(func.count(AnalyticsEvent.id).desc())
        .all()
    )

    top_pages = (
        db.session.query(AnalyticsEvent.path, func.count(AnalyticsEvent.id))
        .filter(
            AnalyticsEvent.name == "page_view",
            AnalyticsEvent.received_at >= since_dt,
            AnalyticsEvent.path.isnot(None),
        )
        .group_by(AnalyticsEvent.path)
        .order_by(func.count(AnalyticsEvent.id).desc())
        .limit(10)
        .all()
    )

    top_stocks = (
        db.session.query(AnalyticsEvent.symbol, func.count(AnalyticsEvent.id))
        .filter(
            AnalyticsEvent.name == "stock_page_viewed",
            AnalyticsEvent.received_at >= since_dt,
            AnalyticsEvent.symbol.isnot(None),
        )
        .group_by(AnalyticsEvent.symbol)
        .order_by(func.count(AnalyticsEvent.id).desc())
        .limit(10)
        .all()
    )

    return jsonify({
        "period_days":      days,
        "total_events":     total_events,
        "page_views":       page_views,
        "event_breakdown":  [{"name": name, "count": cnt} for name, cnt in event_breakdown],
        "top_pages":        [{"path": path, "views": cnt} for path, cnt in top_pages],
        "top_stocks":       [{"symbol": sym,  "views": cnt} for sym,  cnt in top_stocks],
    })
