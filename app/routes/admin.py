"""
/api/admin/health  — Internal system monitoring dashboard
Not exposed to regular users. Returns aggregated metrics for ops use.
"""
from datetime import date, timedelta
from flask import Blueprint, jsonify
from sqlalchemy import func

from app import db
from app.models.opportunity import Opportunity
from app.models.score import RadarScoreHistory
from app.models.regime import MarketRegimeHistory

admin_bp = Blueprint("admin", __name__)


@admin_bp.get("/api/admin/health")
def system_health():
    today     = date.today()
    week_ago  = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # ── Signals & Trades ────────────────────────────────────────────────────────
    signals_today = Opportunity.query.filter_by(run_date=today).count()
    open_trades   = Opportunity.query.filter_by(outcome="PENDING", is_active=True).count()

    sra_open = (
        Opportunity.query
        .filter(Opportunity.opp_type.like("SRA_%"), Opportunity.outcome == "PENDING", Opportunity.is_active == True)
        .all()
    )
    sra_open_count = len(sra_open)

    # ── Grade distribution (open SRA) ───────────────────────────────────────────
    grade_dist = {"A+": 0, "A": 0, "B": 0}
    sra_scores = []
    for o in sra_open:
        snap = o.feature_snapshot or {}
        g = snap.get("sra_grade", "B")
        grade_dist[g] = grade_dist.get(g, 0) + 1
        sc = snap.get("sra_score")
        if sc is not None:
            sra_scores.append(float(sc))

    avg_sra_score = round(sum(sra_scores) / len(sra_scores), 1) if sra_scores else None

    # ── Closed trade performance ─────────────────────────────────────────────────
    closed = (
        Opportunity.query
        .filter(Opportunity.outcome.in_(["WIN", "LOSS", "EXPIRED"]))
        .all()
    )
    total_closed = len(closed)
    wins         = sum(1 for o in closed if o.outcome == "WIN")
    losses       = sum(1 for o in closed if o.outcome == "LOSS")
    win_rate     = round(wins / total_closed * 100, 1) if total_closed > 0 else None

    # ── Knowledge Base ───────────────────────────────────────────────────────────
    kb_size = (
        Opportunity.query
        .filter(Opportunity.opp_type.like("SRA_%"), Opportunity.outcome.in_(["WIN", "LOSS"]))
        .count()
    )
    kb_growth_7d = (
        Opportunity.query
        .filter(
            Opportunity.opp_type.like("SRA_%"),
            Opportunity.outcome.in_(["WIN", "LOSS"]),
            Opportunity.run_date >= week_ago,
        )
        .count()
    )
    kb_growth_30d = (
        Opportunity.query
        .filter(
            Opportunity.opp_type.like("SRA_%"),
            Opportunity.outcome.in_(["WIN", "LOSS"]),
            Opportunity.run_date >= month_ago,
        )
        .count()
    )

    # ── SRA signals generated (last 7 / 30 days) ────────────────────────────────
    sra_7d = (
        Opportunity.query
        .filter(Opportunity.opp_type.like("SRA_%"), Opportunity.run_date >= week_ago)
        .count()
    )
    sra_30d = (
        Opportunity.query
        .filter(Opportunity.opp_type.like("SRA_%"), Opportunity.run_date >= month_ago)
        .count()
    )

    # ── Scored stocks today ──────────────────────────────────────────────────────
    scored_today = RadarScoreHistory.query.filter_by(run_date=today).count()
    scored_week  = (
        db.session.query(func.count(func.distinct(RadarScoreHistory.run_date)))
        .filter(RadarScoreHistory.run_date >= week_ago)
        .scalar() or 0
    )

    # ── Latest regime ────────────────────────────────────────────────────────────
    regime_rec = (
        MarketRegimeHistory.query
        .order_by(MarketRegimeHistory.run_date.desc())
        .first()
    )
    regime_info = {
        "regime":     regime_rec.regime if regime_rec else None,
        "confidence": regime_rec.confidence if regime_rec else None,
        "run_date":   regime_rec.run_date.isoformat() if regime_rec else None,
    } if regime_rec else None

    # ── Response ─────────────────────────────────────────────────────────────────
    return jsonify({
        "as_of": today.isoformat(),
        "signals": {
            "today":        signals_today,
            "sra_open":     sra_open_count,
            "all_open":     open_trades,
            "sra_7d":       sra_7d,
            "sra_30d":      sra_30d,
        },
        "performance": {
            "total_closed": total_closed,
            "wins":         wins,
            "losses":       losses,
            "win_rate":     win_rate,
        },
        "sra": {
            "avg_score":    avg_sra_score,
            "grade_dist":   grade_dist,
        },
        "knowledge_base": {
            "size":         kb_size,
            "growth_7d":    kb_growth_7d,
            "growth_30d":   kb_growth_30d,
        },
        "scanner": {
            "scored_today": scored_today,
            "scan_days_7d": scored_week,
        },
        "regime": regime_info,
    })
