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
    pro_count  = sum(1 for u in all_users if u.is_pro_active())

    users_list = [
        {
            "id":             u.id,
            "email":          u.email,
            "name":           u.name,
            "is_pro":         u.is_pro_active(),
            "pro_expires_at": u.pro_expires_at.isoformat() if u.pro_expires_at else None,
            "created_at":     u.created_at.isoformat() if u.created_at else None,
            "last_login":     u.last_login_at.isoformat() if u.last_login_at else None,
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
    from app.models.scan_log    import ScanLog

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

    sra_7d  = Opportunity.query.filter(
        Opportunity.opp_type.like("SRA_%"),
        Opportunity.run_date >= week_ago,
    ).count()
    sra_30d = Opportunity.query.filter(
        Opportunity.opp_type.like("SRA_%"),
        Opportunity.run_date >= month_ago,
    ).count()
    trend_7d = Opportunity.query.filter(
        Opportunity.opp_type.like("TREND_%"),
        Opportunity.run_date >= week_ago,
    ).count()
    trend_open = Opportunity.query.filter(
        Opportunity.opp_type.like("TREND_%"),
        Opportunity.outcome == "PENDING",
        Opportunity.is_active == True,
    ).count()

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

    try:
        s = ScanLog.query.order_by(ScanLog.id.desc()).first()
        last_scan_info = {
            "run_date":       s.run_date.isoformat() if s else None,
            "status":         s.status               if s else None,
            "stocks_scanned": s.stocks_scanned       if s else None,
            "sra_signals":    s.sra_signals          if s else None,
            "duration_s":     s.duration_seconds     if s else None,
            "error":          s.error_message        if s else None,
        } if s else None
    except Exception:
        last_scan_info = None

    return jsonify({
        "as_of": today.isoformat(),
        "users": {
            "total": total_users,
            "pro":   pro_users,
            "free":  total_users - pro_users,
        },
        "signals": {
            "today":      signals_today,
            "sra_open":   len(sra_open),
            "all_open":   open_trades,
            "sra_7d":     sra_7d,
            "sra_30d":    sra_30d,
            "trend_7d":   trend_7d,
            "trend_open": trend_open,
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
        "last_scan": last_scan_info,
    })


# ── Health detail drill-down (public — for /admin card click-to-expand) ───────

@admin_bp.get("/api/admin/health-detail")
def health_detail():
    """
    On-demand list behind a /admin dashboard card. ?type=<kind>&limit=<n>
    Kept separate from /api/admin/health (which is polled every 60s) so the
    heavier per-row queries only run when a user actually opens a card.
    """
    from app.models.opportunity import Opportunity
    from app.models.score       import RadarScoreHistory

    kind = request.args.get("type", "")
    try:
        limit = min(int(request.args.get("limit", 30)), 100)
    except (ValueError, TypeError):
        limit = 30
    today = date.today()

    def _classify_mf_reason(mf_ratio, snap, entry_price, current_price):
        """
        Classify WHY money is flowing out.
        Returns (reason_key, reason_ar).

        PROFIT_TAKING  — price rose past entry, people locking in gains (temporary)
        PANIC          — large volume spike or bear regime, fear-driven selling (opportunity)
        DISTRIBUTION   — gradual institutional exit, stock still near/below entry (caution)
        """
        rsi        = snap.get("rsi") or snap.get("rsi_at_low")
        rvol_spike = snap.get("rvol_spike")
        regime     = (snap.get("regime") or "").upper()

        # Price rose significantly after signal → people locking profits
        if entry_price and current_price and current_price > entry_price * 1.06:
            return "PROFIT_TAKING", "جني أرباح"

        # RSI was overbought at signal time → momentum extended, profit taking
        if rsi and rsi > 68:
            return "PROFIT_TAKING", "جني أرباح"

        # High volume spike → panic / fear-driven selling (often a bottom signal)
        if rvol_spike and rvol_spike > 3.0:
            return "PANIC", "ذعر بيع"

        # Very strong outflow in a fearful market → panic
        if mf_ratio is not None and mf_ratio < -0.5 and regime in ("BEAR", "VOLATILE"):
            return "PANIC", "ذعر بيع"

        # Default: gradual institutional distribution
        return "DISTRIBUTION", "توزيع محتمل"

    def _opp_row(o):
        snap  = o.feature_snapshot or {}
        st    = o.stock

        # ── Pivot Points from latest session OHLC ─────────────────────────
        pivot = r1 = r2 = s1 = s2 = None
        if st and st.day_high and st.day_low and st.last_price:
            h, l, c = st.day_high, st.day_low, st.last_price
            p    = (h + l + c) / 3
            pivot = round(p, 2)
            r1    = round(2 * p - l, 2)
            r2    = round(p + (h - l), 2)
            s1    = round(2 * p - h, 2)
            s2    = round(p - (h - l), 2)

        # ── Money Flow Direction ───────────────────────────────────────────
        mf_dir = mf_ratio = mf_reason = mf_reason_ar = None
        if st and st.day_high and st.day_low and st.last_price:
            h, l, c = st.day_high, st.day_low, st.last_price
            if h != l:
                ratio    = (2 * c - h - l) / (h - l)
                mf_ratio = round(ratio, 2)
                mf_dir   = "IN" if ratio > 0 else "OUT"
            else:
                mf_dir, mf_ratio = "NEUTRAL", 0.0

            if mf_dir == "OUT":
                mf_reason, mf_reason_ar = _classify_mf_reason(
                    mf_ratio, snap, o.entry_price, st.last_price
                )

        # ── P/B Ratio ─────────────────────────────────────────────────────
        pb_ratio = None
        if st and st.last_price and getattr(st, "book_value", None):
            try:
                pb_ratio = round(st.last_price / st.book_value, 2)
            except (ZeroDivisionError, TypeError):
                pass

        # ── Why signals & KB context (from feature_snapshot) ──────────────
        why_signals   = snap.get("signals") or snap.get("reasons") or []
        regime        = snap.get("regime")
        breadth_pct   = snap.get("market_breadth_pct")
        similar_cases = snap.get("similar_cases", 0)
        win_rate_pct  = snap.get("historical_win_rate", 0.0)

        return {
            "symbol":         st.symbol    if st else None,
            "name_ar":        st.name_ar   if st else None,
            "is_sharia":      st.is_sharia if st else False,
            "opp_type":       o.opp_type,
            "grade":          snap.get("sra_grade") or (o.opp_type or "").replace("SRA_", "").replace("_PLUS", "+"),
            "score":          o.radar_score,
            "outcome":        o.outcome,
            "pnl_pct":        o.pnl_pct,
            "entry":          o.entry_price,
            "tp1":            o.tp1_price,
            "sl":             o.sl_price,
            "rr":             o.rr_ratio,
            "run_date":       o.run_date.isoformat()  if o.run_date  else None,
            "closed_at":      o.closed_at.isoformat() if o.closed_at else None,
            # new
            "pivot":          pivot,
            "r1":             r1,
            "r2":             r2,
            "s1":             s1,
            "s2":             s2,
            "money_flow_dir":   mf_dir,
            "money_flow_ratio": mf_ratio,
            "mf_reason":        mf_reason,
            "mf_reason_ar":     mf_reason_ar,
            "pb_ratio":       pb_ratio,
            "why_signals":    why_signals,
            "regime":         regime,
            "breadth_pct":    breadth_pct,
            "similar_cases":  similar_cases,
            "win_rate_pct":   win_rate_pct,
        }

    if kind == "signals_today":
        rows = (Opportunity.query.filter_by(run_date=today)
                .order_by(Opportunity.radar_score.desc()).limit(limit).all())
        items = [_opp_row(o) for o in rows]

    elif kind == "sra_open":
        rows = (Opportunity.query
                .filter(Opportunity.opp_type.like("SRA_%"),
                        Opportunity.outcome == "PENDING", Opportunity.is_active.is_(True))
                .order_by(Opportunity.radar_score.desc()).limit(limit).all())
        items = [_opp_row(o) for o in rows]

    elif kind in ("wins", "losses"):
        outcome = "WIN" if kind == "wins" else "LOSS"
        rows = (Opportunity.query.filter_by(outcome=outcome)
                .order_by(Opportunity.closed_at.desc()).limit(limit).all())
        items = [_opp_row(o) for o in rows]

    elif kind == "kb":
        rows = (Opportunity.query
                .filter(Opportunity.opp_type.like("SRA_%"), Opportunity.outcome.in_(["WIN", "LOSS"]))
                .order_by(Opportunity.closed_at.desc()).limit(limit).all())
        items = [_opp_row(o) for o in rows]

    elif kind == "scored_today":
        rows = (db.session.query(RadarScoreHistory, Stock)
                .join(Stock, RadarScoreHistory.stock_id == Stock.id)
                .filter(RadarScoreHistory.run_date == today)
                .order_by(RadarScoreHistory.score.desc()).limit(limit).all())
        items = [
            {"symbol": s.symbol, "name_ar": s.name_ar, "score": round(r.score, 1) if r.score is not None else None,
             "run_date": r.run_date.isoformat() if r.run_date else None}
            for r, s in rows
        ]

    elif kind == "signals_week":
        week_ago = today - timedelta(days=7)
        rows = (Opportunity.query
                .filter(Opportunity.run_date >= week_ago)
                .order_by(Opportunity.run_date.desc(), Opportunity.radar_score.desc())
                .limit(limit).all())
        items = [_opp_row(o) for o in rows]

    else:
        return jsonify({"error": f"unknown type '{kind}'"}), 400

    return jsonify({"type": kind, "count": len(items), "items": items})


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
                "id":             u.id,
                "email":          u.email,
                "name":           u.name,
                "is_pro":         u.is_pro_active(),
                "pro_expires_at": u.pro_expires_at.isoformat() if u.pro_expires_at else None,
                "is_active":      u.is_active,
                "created_at":     u.created_at.isoformat() if u.created_at else None,
                "last_login":     u.last_login_at.isoformat() if u.last_login_at else None,
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

    # منح يدوي من الأدمن = دائم بلا انتهاء (مختلف عن الاشتراك المدفوع)
    user.is_pro         = True
    user.pro_expires_at = None
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

    user.is_pro         = False
    user.pro_expires_at = None
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
        from app.models.payment import PLAN_DURATION_DAYS
        days = PLAN_DURATION_DAYS.get(payment.plan, 30)
        now  = datetime.now(timezone.utc)
        # لو عنده اشتراك سارٍ لسه، مدّد من تاريخ انتهائه (متجدّد قبل الانتهاء = مايضيعش أيام)
        # غير كده، ابدأ من دلوقتي (سواء أول اشتراك أو كان منتهي)
        base = user.pro_expires_at if (user.pro_expires_at and user.pro_expires_at > now) else now
        user.pro_expires_at = base + timedelta(days=days)
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


# ── Trend Monitor (public — Admin dual-run dashboard) ─────────────────────────
# Read-only aggregate, no auth (same pattern as /api/admin/health). Additive:
# nothing else changes. Families are derived from opp_type prefix (no schema).

_RESEARCH_EXPECTATIONS = {
    # From docs/research/. Live outcomes are GROSS (no slippage), so these are
    # gross-ish reference bands — used only to flag large drift, not exact match.
    "signals_per_day_min": 1.0,
    "signals_per_day_max": 3.0,
    "win_rate":   46.0,
    "pf":         1.6,
    "avg_return": 1.3,
}


def _opp_family(opp_type: str) -> str:
    ot = opp_type or ""
    if ot.startswith("TREND_"):
        return "trend"
    if ot.startswith("SRA_"):
        return "sra"
    return "momentum"


@admin_bp.get("/api/admin/trend-monitor")
def trend_monitor():
    """
    Admin dual-run dashboard data (public, like /api/admin/health).
    ?date=YYYY-MM-DD replays a past day (signals/pool/stats as of that date).
    """
    from app.models.opportunity import Opportunity
    from app.models.score       import RadarScoreHistory
    from app.models.scan_log    import ScanLog

    date_arg = request.args.get("date")
    try:
        sel = datetime.strptime(date_arg, "%Y-%m-%d").date() if date_arg else date.today()
    except ValueError:
        sel = date.today()
    since_30 = sel - timedelta(days=30)

    # ── Signals on the selected day (with full details) ───────────────────────
    day_opps = Opportunity.query.filter_by(run_date=sel).all()

    def _sig(o):
        snap = o.feature_snapshot or {}
        return {
            "symbol":   o.stock.symbol if o.stock else None,
            "opp_type": o.opp_type,
            "grade":    (o.opp_type or "_").split("_")[-1],
            "score":    o.radar_score,
            "quality":  o.signal_quality,
            "entry":    o.entry_price,
            "sl":       o.sl_price,
            "tp1":      o.tp1_price,
            "tp2":      o.tp2_price,
            "rr":       o.rr_ratio,
            "outcome":  o.outcome,
            "adx":      snap.get("adx"),
            "rsi":      snap.get("rsi"),
            "ema_fast": snap.get("ema_fast"),
            "ema_slow": snap.get("ema_slow"),
            "atr":      snap.get("atr"),
            "adt":      snap.get("adt"),
            "reasons":  snap.get("reasons", []),
        }

    trend_sigs = [_sig(o) for o in day_opps if _opp_family(o.opp_type) == "trend"]
    sra_sigs   = [_sig(o) for o in day_opps if _opp_family(o.opp_type) == "sra"]

    # Radar Score pool (score >= 60) on the selected day
    pool_rows = (
        db.session.query(RadarScoreHistory, Stock)
        .join(Stock, RadarScoreHistory.stock_id == Stock.id)
        .filter(RadarScoreHistory.run_date == sel, RadarScoreHistory.score >= 60)
        .order_by(RadarScoreHistory.score.desc())
        .all()
    )
    radar_pool = [
        {"symbol": s.symbol, "score": round(r.score, 1) if r.score is not None else None,
         "adx": r.adx, "rsi": r.rsi}
        for r, s in pool_rows
    ]

    # ── Overlap on the selected day ───────────────────────────────────────────
    trend_ids = {o.stock_id for o in day_opps if _opp_family(o.opp_type) == "trend"}
    sra_ids   = {o.stock_id for o in day_opps if _opp_family(o.opp_type) == "sra"}
    radar_ids = {r.stock_id for r, _ in pool_rows}
    daily_stats = {
        "trend":             len(trend_ids),
        "sra":               len(sra_ids),
        "radar":             len(radar_ids),
        "overlap_trend_sra": len(trend_ids & sra_ids),
        "trend_only":        len(trend_ids - sra_ids - radar_ids),
        "sra_only":          len(sra_ids - trend_ids - radar_ids),
        "radar_only":        len(radar_ids - trend_ids - sra_ids),
    }

    # ── Last 30 days table (counts + trend/sra overlap per day) ───────────────
    win_opps = Opportunity.query.filter(
        Opportunity.run_date >= since_30, Opportunity.run_date <= sel
    ).all()
    radar_30 = (
        db.session.query(RadarScoreHistory.run_date, RadarScoreHistory.stock_id)
        .filter(RadarScoreHistory.run_date >= since_30,
                RadarScoreHistory.run_date <= sel,
                RadarScoreHistory.score >= 60)
        .all()
    )
    by_day: dict = {}
    for o in win_opps:
        bucket = by_day.setdefault(o.run_date, {"trend": set(), "sra": set(), "radar": set()})
        fam = _opp_family(o.opp_type)
        if fam in ("trend", "sra"):
            bucket[fam].add(o.stock_id)
    for rd, sid in radar_30:
        by_day.setdefault(rd, {"trend": set(), "sra": set(), "radar": set()})["radar"].add(sid)
    last_30 = [
        {
            "date":    d.isoformat(),
            "trend":   len(v["trend"]),
            "sra":     len(v["sra"]),
            "radar":   len(v["radar"]),
            "overlap": len(v["trend"] & v["sra"]),
        }
        for d, v in sorted(by_day.items(), reverse=True)
    ]

    # ── Outcome comparison (all-time, by family) ──────────────────────────────
    def _family_outcomes(prefix):
        rows    = Opportunity.query.filter(Opportunity.opp_type.like(prefix)).all()
        pending = [o for o in rows if o.outcome == "PENDING"]
        closed  = [o for o in rows if o.outcome in ("WIN", "LOSS")]
        wins    = [o for o in closed if o.outcome == "WIN"]
        losses  = [o for o in closed if o.outcome == "LOSS"]
        gains   = sum(o.pnl_pct for o in wins   if o.pnl_pct is not None)
        drops   = sum(o.pnl_pct for o in losses if o.pnl_pct is not None)
        pnls    = [o.pnl_pct   for o in closed if o.pnl_pct   is not None]
        holds   = [o.hold_days for o in closed if o.hold_days is not None]
        # Max drawdown of the sequential closed-trade equity curve (by close date)
        seq = sorted([o for o in closed if o.pnl_pct is not None],
                     key=lambda o: (o.closed_at or o.run_date or date.min))
        cum = peak = maxdd = 0.0
        for o in seq:
            cum += o.pnl_pct
            peak = max(peak, cum)
            maxdd = max(maxdd, peak - cum)
        return {
            "pending":       len(pending),
            "closed":        len(closed),
            "wins":          len(wins),
            "losses":        len(losses),
            "win_rate":      round(len(wins) / len(closed) * 100, 1) if closed else None,
            "avg_return":    round(sum(pnls) / len(pnls), 2) if pnls else None,
            "pf":            round(gains / abs(drops), 2) if drops else (None if not closed else 999),
            "avg_hold_days": round(sum(holds) / len(holds), 1) if holds else None,
            "max_dd":        round(maxdd, 1) if seq else None,
        }

    trend_out = _family_outcomes("TREND_%")
    sra_out   = _family_outcomes("SRA_%")

    # ── Research validation (drift detector) ──────────────────────────────────
    # Measure signals/day only over days the trend engine was actually live.
    # Days before it shipped have trend=0 by definition and would otherwise
    # look like a permanent drift for the first 30 days after launch.
    first_trend = (db.session.query(func.min(Opportunity.run_date))
                   .filter(Opportunity.opp_type.like("TREND_%")).scalar())
    active_rows = [x for x in last_30 if first_trend and x["date"] >= first_trend.isoformat()]
    sig_per_day = (round(sum(x["trend"] for x in active_rows) / len(active_rows), 2)
                   if active_rows else None)
    exp   = _RESEARCH_EXPECTATIONS
    drift = []
    if trend_out["closed"] >= 10:
        if trend_out["win_rate"] is not None and abs(trend_out["win_rate"] - exp["win_rate"]) > 15:
            drift.append("win_rate")
        if trend_out["pf"] is not None and trend_out["pf"] != 999 and abs(trend_out["pf"] - exp["pf"]) > 0.5:
            drift.append("pf")
    # Needs a real run history before a signal-rate verdict is meaningful
    if sig_per_day is not None and len(active_rows) >= 5 and (sig_per_day < 0.3 or sig_per_day > 6):
        drift.append("signals_per_day")

    validation = {
        "expected": exp,
        "actual": {
            "signals_per_day": sig_per_day,
            "win_rate":        trend_out["win_rate"],
            "pf":              trend_out["pf"],
            "avg_return":      trend_out["avg_return"],
        },
        "sample_closed": trend_out["closed"],
        "status":  "collecting" if trend_out["closed"] < 10 else ("drift" if drift else "match"),
        "drift_fields": drift,
    }

    # ── Scan logs (last 10 runs, trend count derived) ─────────────────────────
    scan_logs = []
    for lg in ScanLog.query.order_by(ScanLog.run_date.desc()).limit(10).all():
        t_cnt = Opportunity.query.filter(
            Opportunity.opp_type.like("TREND_%"), Opportunity.run_date == lg.run_date
        ).count()
        scan_logs.append({
            "run_date":         lg.run_date.isoformat() if lg.run_date else None,
            "status":           lg.status,
            "stocks_scanned":   lg.stocks_scanned,
            "trend":            t_cnt,
            "sra":              getattr(lg, "sra_signals", None),
            "momentum":         getattr(lg, "momentum_signals", None),
            "started_at":       lg.started_at.isoformat()  if getattr(lg, "started_at", None)  else None,
            "finished_at":      lg.finished_at.isoformat() if getattr(lg, "finished_at", None) else None,
            "duration_seconds": getattr(lg, "duration_seconds", None),
        })

    # ── Overlap with actual symbols (selected day) ────────────────────────────
    sym_of = {o.stock_id: (o.stock.symbol if o.stock else str(o.stock_id)) for o in day_opps}
    trend_syms = {sym_of[i] for i in trend_ids}
    sra_syms   = {sym_of[i] for i in sra_ids}
    overlap = {
        "trend_only": sorted(trend_syms - sra_syms),
        "both":       sorted(trend_syms & sra_syms),
        "sra_only":   sorted(sra_syms - trend_syms),
    }

    # ── Research status ───────────────────────────────────────────────────────
    last_log    = ScanLog.query.order_by(ScanLog.run_date.desc()).first()
    last_closed = (Opportunity.query.filter(Opportunity.closed_at.isnot(None))
                   .order_by(Opportunity.closed_at.desc()).first())
    research_status = {
        "current_engine":      "SRA (primary) — migrating to Trend Initiation",
        "trend_version":       "TREND_v1",
        "research_version":    "v1.0",
        "last_scan":           last_log.run_date.isoformat() if last_log and last_log.run_date else None,
        "last_outcome_update": last_closed.closed_at.isoformat() if last_closed and last_closed.closed_at else None,
        "stocks_analyzed":     last_log.stocks_scanned if last_log else None,
    }

    # ── Research Gate (promotion criteria) ────────────────────────────────────
    trend_active_days = len({x["date"] for x in last_30 if x["trend"] > 0})
    recent_failed = ScanLog.query.filter(
        ScanLog.status == "failed", ScanLog.run_date >= since_30
    ).count() > 0
    t_pf, s_pf = trend_out["pf"], sra_out["pf"]
    if trend_out["closed"] >= 5 and sra_out["closed"] >= 5 and t_pf is not None and s_pf is not None:
        pf_beats = "pass" if (t_pf != 999 and t_pf > s_pf) else "fail"
    else:
        pf_beats = "wait"
    gate = [
        {"criterion": "Trend يعمل بدون أخطاء", "status": "fail" if recent_failed else "pass"},
        {"criterion": "Research = Production",
         "status": "pass" if validation["status"] == "match" else ("wait" if validation["status"] == "collecting" else "fail")},
        {"criterion": "لا يوجد Drift",
         "status": "fail" if validation["drift_fields"]
                   else ("wait" if validation["status"] == "collecting" else "pass")},
        {"criterion": "14 يوم تشغيل متواصل",
         "status": "pass" if trend_active_days >= 14 else "wait", "detail": f"{trend_active_days}/14"},
        {"criterion": "PF أعلى من SRA", "status": pf_beats},
    ]
    gate_ready = all(g["status"] == "pass" for g in gate)
    gate.append({"criterion": "جاهز للتحويل إلى Primary Engine",
                 "status": "pass" if gate_ready else "wait"})

    return jsonify({
        "as_of":     date.today().isoformat(),
        "date":      sel.isoformat(),
        "is_replay": sel != date.today(),
        "research_status": research_status,
        "research_gate":   gate,
        "today":     {"trend": trend_sigs, "sra": sra_sigs, "radar_pool": radar_pool},
        "daily_stats":  daily_stats,
        "overlap":      overlap,
        "last_30_days": last_30,
        "outcomes":     {"trend": trend_out, "sra": sra_out},
        "validation":   validation,
        "scan_logs":    scan_logs,
    })
