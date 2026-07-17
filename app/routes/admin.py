"""
Admin-only endpoints — all protected by BOT_API_KEY header or query param.

GET  /api/admin/health              — system health (public, for frontend dashboard)
GET  /api/admin/dashboard           — full dashboard (JWT auth, owner email only)
GET  /api/admin/users               — list all registered users
POST /api/admin/grant-pro           — set is_pro=True for a given email
POST /api/admin/revoke-pro          — set is_pro=False for a given email
GET  /api/admin/analytics           — aggregated event counts / page views
GET  /api/admin/payments            — list pending payments with receipt images (JWT owner)
POST /api/admin/payments/<id>/approve — approve payment → activate PRO (JWT owner)
POST /api/admin/payments/<id>/reject  — reject payment with note (JWT owner)
GET  /api/admin/sharia              — list current Sharia stocks in DB
POST /api/admin/sharia/sync         — update Sharia list from supplied symbols (EGX rebalance)
"""
import os
from datetime import date, timedelta, datetime, timezone
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func

from app import db
from app.models.user import User
from app.models.stock import Stock
from app.models.analytics import AnalyticsEvent
from app.models.payment import Payment

admin_bp = Blueprint("admin", __name__)


def _check_key():
    """Return 401 if BOT_API_KEY missing or wrong."""
    api_key  = request.headers.get("X-API-Key") or request.args.get("api_key")
    expected = os.getenv("BOT_API_KEY")
    if not expected or api_key != expected:
        return jsonify({"error": "unauthorized"}), 401
    return None


# ── Owner dashboard (JWT auth, email match) ───────────────────────────────────

def _get_analytics_data(days: int = 7):
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    page_views = AnalyticsEvent.query.filter(
        AnalyticsEvent.name == "page_view",
        AnalyticsEvent.received_at >= since_dt,
    ).count()
    total_events = AnalyticsEvent.query.filter(AnalyticsEvent.received_at >= since_dt).count()
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
        .limit(10).all()
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
        .limit(10).all()
    )
    return {
        "period_days":     days,
        "total_events":    total_events,
        "page_views":      page_views,
        "event_breakdown": [{"name": n, "count": c} for n, c in event_breakdown],
        "top_pages":       [{"path": p, "views": c} for p, c in top_pages],
        "top_stocks":      [{"symbol": s, "views": c} for s, c in top_stocks],
    }


@admin_bp.get("/api/admin/dashboard")
@jwt_required()
def owner_dashboard():
    """Full dashboard — JWT auth, only the ADMIN_EMAIL owner can access."""
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()

    if not user or not admin_email or user.email.lower() != admin_email:
        return jsonify({"error": "غير مصرح"}), 403

    days = int(request.args.get("days", 7))

    # Users
    all_users = User.query.order_by(User.created_at.desc()).all()
    pro_count  = sum(1 for u in all_users if u.is_pro)

    users_list = [
        {
            "id":         u.id,
            "email":      u.email,
            "name":       u.name,
            "is_pro":     u.is_pro,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login_at.isoformat() if u.last_login_at else None,
        }
        for u in all_users
    ]

    return jsonify({
        "users": {
            "total": len(all_users),
            "pro":   pro_count,
            "free":  len(all_users) - pro_count,
            "list":  users_list,
        },
        "analytics": _get_analytics_data(days),
    })


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
    expired      = sum(1 for o in closed if o.outcome == "EXPIRED")
    # Win rate excludes EXPIRED — only counts decided outcomes (WIN vs LOSS)
    decided  = wins + losses
    win_rate = round(wins / decided * 100, 1) if decided > 0 else None

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
            "expired":      expired,
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
    return jsonify(_get_analytics_data(days))


# ── Payments review (JWT owner) ───────────────────────────────────────────────

def _require_owner():
    """Return (user, None) if JWT owner, else (None, error_response)."""
    from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
    try:
        verify_jwt_in_request()
    except Exception:
        return None, (jsonify({"error": "يجب تسجيل الدخول"}), 401)
    uid        = get_jwt_identity()
    user       = User.query.get(int(uid))
    admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    if not user or not admin_email or user.email.lower() != admin_email:
        return None, (jsonify({"error": "غير مصرح"}), 403)
    return user, None


@admin_bp.get("/api/admin/payments")
def list_payments():
    """All payments — pending first — with receipt images. JWT owner only."""
    _, err = _require_owner()
    if err:
        return err

    status_filter = request.args.get("status")   # pending | completed | rejected | all
    query = Payment.query.order_by(Payment.created_at.desc())
    if status_filter and status_filter != "all":
        query = query.filter_by(status=status_filter)

    payments = query.limit(100).all()
    return jsonify({
        "total":    len(payments),
        "payments": [p.to_dict_admin() for p in payments],
    })


@admin_bp.post("/api/admin/payments/<int:payment_id>/approve")
def approve_payment(payment_id: int):
    """Approve a pending payment → activate PRO. JWT owner only."""
    _, err = _require_owner()
    if err:
        return err

    payment = db.session.get(Payment, payment_id)
    if not payment:
        return jsonify({"error": "الدفعة غير موجودة"}), 404
    if payment.status != "pending":
        return jsonify({"error": f"الدفعة بحالة {payment.status} ولا يمكن الموافقة عليها"}), 422

    payment.status = "completed"
    user = db.session.get(User, payment.user_id)
    if user:
        user.is_pro = True
        # لو المستخدم جاء بدعوة → أعطِ صاحب الدعوة credit
        if user.referred_by_id:
            referrer = db.session.get(User, user.referred_by_id)
            if referrer:
                referrer.discount_credits = (referrer.discount_credits or 0) + 1
    db.session.commit()

    return jsonify({"ok": True, "payment_id": payment_id, "user_email": user.email if user else None})


@admin_bp.post("/api/admin/payments/<int:payment_id>/reject")
def reject_payment(payment_id: int):
    """Reject a pending payment with optional note. JWT owner only."""
    _, err = _require_owner()
    if err:
        return err

    payment = db.session.get(Payment, payment_id)
    if not payment:
        return jsonify({"error": "الدفعة غير موجودة"}), 404
    if payment.status != "pending":
        return jsonify({"error": f"الدفعة بحالة {payment.status}"}), 422

    body = request.get_json(silent=True) or {}
    payment.status     = "rejected"
    payment.admin_note = body.get("note", "").strip() or None
    db.session.commit()

    return jsonify({"ok": True, "payment_id": payment_id})


# ── Trigger daily scan manually ──────────────────────────────────────────────

@admin_bp.post("/api/admin/trigger-scan")
def trigger_scan():
    """Trigger the daily scan pipeline in a background thread. Protected by BOT_API_KEY."""
    err = _check_key()
    if err:
        return err

    import threading
    from flask import current_app

    app = current_app._get_current_object()

    def _run():
        from app.jobs.daily_scan import run_daily_scan
        run_daily_scan(app)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return jsonify({"ok": True, "message": "daily scan started in background"}), 200


# ── Scan logs ─────────────────────────────────────────────────────────────────

@admin_bp.get("/api/admin/scan-logs")
def scan_logs():
    """Last N daily scan log entries. Protected by BOT_API_KEY."""
    err = _check_key()
    if err:
        return err

    from app.models.scan_log import ScanLog

    try:
        limit = min(int(request.args.get("limit", 10)), 50)
    except (ValueError, TypeError):
        limit = 10
    logs  = ScanLog.query.order_by(ScanLog.run_date.desc(), ScanLog.id.desc()).limit(limit).all()
    return jsonify({"count": len(logs), "logs": [l.to_dict() for l in logs]})


# ── KB Snapshot (weekly — called by GitHub Actions every Thursday) ────────────

@admin_bp.get("/api/admin/kb-snapshot")
def kb_snapshot():
    """Return a full Knowledge Base snapshot for archiving. Protected by BOT_API_KEY."""
    err = _check_key()
    if err:
        return err

    from app.models.opportunity import Opportunity

    closed = (
        Opportunity.query
        .filter(
            Opportunity.opp_type.like("SRA_%"),
            Opportunity.outcome.in_(["WIN", "LOSS", "EXPIRED"]),
        )
        .all()
    )

    total   = len(closed)
    wins    = [o for o in closed if o.outcome == "WIN"]
    losses  = [o for o in closed if o.outcome == "LOSS"]
    expired = [o for o in closed if o.outcome == "EXPIRED"]

    decided  = len(wins) + len(losses)
    win_rate = round(len(wins) / decided * 100, 1) if decided > 0 else None

    # avg_pnl uses the same population as win_rate — decided trades only (excludes EXPIRED)
    pnls     = [o.pnl_pct for o in wins + losses if o.pnl_pct is not None]
    avg_pnl  = round(sum(pnls) / len(pnls), 2) if pnls else None

    grade_breakdown = {}
    for o in closed:
        g = o.opp_type.replace("SRA_", "")
        if g not in grade_breakdown:
            grade_breakdown[g] = {"total": 0, "wins": 0, "losses": 0, "expired": 0}
        grade_breakdown[g]["total"] += 1
        if o.outcome == "WIN":
            grade_breakdown[g]["wins"] += 1
        elif o.outcome == "LOSS":
            grade_breakdown[g]["losses"] += 1
        else:
            grade_breakdown[g]["expired"] += 1

    return jsonify({
        "snapshot_date": date.today().isoformat(),
        "size":          total,
        "win_rate":      win_rate,
        "avg_pnl_pct":   avg_pnl,
        "breakdown": {
            "wins":    len(wins),
            "losses":  len(losses),
            "expired": len(expired),
        },
        "by_grade": grade_breakdown,
    })


# ── Sharia sync (EGX rebalance every ~6 months) ───────────────────────────────

@admin_bp.get("/api/admin/sharia")
def list_sharia_stocks():
    """List all stocks currently marked is_sharia=True in DB."""
    err = _check_key()
    if err:
        return err

    stocks = Stock.query.filter_by(is_sharia=True).order_by(Stock.symbol).all()
    return jsonify({
        "count":  len(stocks),
        "stocks": [{"symbol": s.symbol, "name_ar": s.name_ar, "sector": s.sector} for s in stocks],
        "note":   "EGX 33 Shariah index rebalances every ~6 months (Jan & Jul). Use POST /api/admin/sharia/sync to update.",
    })


@admin_bp.post("/api/admin/sharia/sync")
def sync_sharia_stocks():
    """
    Update is_sharia flags to match the supplied EGX official list.

    Body: { "symbols": ["ADIB", "SAUD", "FAIT", ...] }

    Returns a summary of what changed. Run after each EGX rebalancing.
    """
    err = _check_key()
    if err:
        return err

    body    = request.get_json(silent=True) or {}
    symbols = body.get("symbols")
    if not symbols or not isinstance(symbols, list):
        return jsonify({"error": "symbols array required"}), 400

    new_sharia = {s.strip().upper().replace(".CA", "") for s in symbols if s.strip()}
    if len(new_sharia) < 10:
        return jsonify({"error": f"Only {len(new_sharia)} symbols — expected 30+. Check your list."}), 400

    all_stocks  = Stock.query.all()
    added       = []
    removed     = []
    not_in_db   = []

    for sym in new_sharia:
        stock = next((s for s in all_stocks if s.symbol == sym), None)
        if stock is None:
            not_in_db.append(sym)
        elif not stock.is_sharia:
            stock.is_sharia = True
            added.append(sym)

    for stock in all_stocks:
        if stock.is_sharia and stock.symbol not in new_sharia:
            stock.is_sharia = False
            removed.append(stock.symbol)

    db.session.commit()

    return jsonify({
        "ok":         True,
        "egx_count":  len(new_sharia),
        "added":      sorted(added),
        "removed":    sorted(removed),
        "not_in_db":  sorted(not_in_db),
        "message":    f"+{len(added)} sharia, -{len(removed)} sharia, {len(not_in_db)} symbols not found in DB",
    })


@admin_bp.get("/api/admin/trend-status")
def trend_status():
    """
    Dual-run monitoring — trend vs SRA vs momentum signals + outcomes.

    Families are derived from the opp_type prefix (no schema dependency):
      TREND_* | SRA_* | everything else = momentum.
    Use this to watch the Trend-Initiation migration without reading the DB or logs.
    """
    err = _check_key()
    if err:
        return err

    from app.models.opportunity import Opportunity

    today    = date.today()
    since_30 = today - timedelta(days=30)

    def _count(pattern, *, run_date=None, since=None, exclude=None):
        q = Opportunity.query
        if pattern:
            q = q.filter(Opportunity.opp_type.like(pattern))
        for ex in (exclude or []):
            q = q.filter(~Opportunity.opp_type.like(ex))
        if run_date is not None:
            q = q.filter(Opportunity.run_date == run_date)
        if since is not None:
            q = q.filter(Opportunity.run_date >= since)
        return q.count()

    def _outcomes(pattern, since):
        rows = Opportunity.query.filter(
            Opportunity.opp_type.like(pattern),
            Opportunity.run_date >= since,
            Opportunity.outcome.in_(["WIN", "LOSS"]),
        ).all()
        wins   = sum(1 for o in rows if o.outcome == "WIN")
        gains  = sum(o.pnl_pct for o in rows if o.pnl_pct and o.pnl_pct > 0)
        drops  = sum(o.pnl_pct for o in rows if o.pnl_pct and o.pnl_pct <= 0)
        return {
            "closed":   len(rows),
            "wins":     wins,
            "losses":   len(rows) - wins,
            "win_rate": round(wins / len(rows) * 100, 1) if rows else None,
            "pf":       round(gains / abs(drops), 2) if drops else (None if not rows else 999),
        }

    return jsonify({
        "as_of": today.isoformat(),
        "today": {
            "trend":    _count("TREND_%", run_date=today),
            "sra":      _count("SRA_%",   run_date=today),
            "momentum": _count(None, run_date=today, exclude=["TREND_%", "SRA_%"]),
        },
        "last_30_days": {
            "trend": _count("TREND_%", since=since_30),
            "sra":   _count("SRA_%",   since=since_30),
        },
        "outcomes_30d": {
            "trend": _outcomes("TREND_%", since_30),
            "sra":   _outcomes("SRA_%",   since_30),
        },
    })
