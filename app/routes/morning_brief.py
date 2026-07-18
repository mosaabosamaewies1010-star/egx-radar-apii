"""
GET /api/morning-brief — daily market brief (cached 1 h)
"""
from flask import Blueprint, jsonify
from sqlalchemy import func

from app import db, cache
from app.models.regime import MarketRegimeHistory
from app.models.score import RadarScoreHistory
from app.models.stock import Stock
from app.models.opportunity import Opportunity
from app.utils.pro_guard import require_pro

morning_brief_bp = Blueprint("morning_brief", __name__)


@morning_brief_bp.get("/api/morning-brief")
def morning_brief():
    err = require_pro()
    if err:
        return err
    # Latest two regime rows for EGX30 day-over-day change
    regimes = (MarketRegimeHistory.query
               .order_by(MarketRegimeHistory.run_date.desc())
               .limit(2).all())
    regime_today = regimes[0] if regimes else None
    regime_prev  = regimes[1] if len(regimes) > 1 else None

    egx30_close      = regime_today.egx30_close if regime_today else None
    egx30_change_pct = None
    if (regime_today and regime_prev
            and regime_today.egx30_close and regime_prev.egx30_close):
        egx30_change_pct = round(
            (regime_today.egx30_close - regime_prev.egx30_close)
            / regime_prev.egx30_close * 100, 2
        )

    # Latest scored date
    latest_date = db.session.query(func.max(RadarScoreHistory.run_date)).scalar()

    top_scores   = []
    top_rvol     = []
    scored_count = 0

    if latest_date:
        rows = (db.session.query(RadarScoreHistory, Stock)
                .join(Stock, RadarScoreHistory.stock_id == Stock.id)
                .filter(RadarScoreHistory.run_date == latest_date)
                .all())
        scored_count = len(rows)

        by_score = sorted(rows, key=lambda r: r[0].score, reverse=True)[:5]
        top_scores = [
            {
                "symbol":          st.symbol,
                "name_ar":         st.name_ar,
                "sector":          st.sector,
                "is_sharia":       st.is_sharia,
                "score":           round(sc.score, 1),
                "last_change_pct": st.last_change_pct,
            }
            for sc, st in by_score
        ]

        by_rvol = sorted(rows, key=lambda r: r[0].rvol or 0, reverse=True)[:5]
        top_rvol = [
            {
                "symbol":  st.symbol,
                "name_ar": st.name_ar,
                "rvol":    round(sc.rvol or 0, 2),
                "score":   round(sc.score, 1),
            }
            for sc, st in by_rvol
        ]

    # Breadth from latest regime record
    breadth = None
    if regime_today and regime_today.advancing is not None:
        breadth = {
            "advancing": regime_today.advancing,
            "declining": regime_today.declining,
            "unchanged": regime_today.unchanged,
        }

    # New opportunities from latest opportunity date
    # dual-run: TREND_ signals are admin-only until validated
    latest_opp_date = (db.session.query(func.max(Opportunity.run_date))
                       .filter(~Opportunity.opp_type.like("TREND_%")).scalar())
    new_opportunities = []
    if latest_opp_date:
        opps = (db.session.query(Opportunity, Stock)
                .join(Stock, Opportunity.stock_id == Stock.id)
                .filter(
                    Opportunity.run_date == latest_opp_date,
                    Opportunity.outcome  == "PENDING",
                    Opportunity.is_active == True,
                    ~Opportunity.opp_type.like("TREND_%"),
                )
                .order_by(Opportunity.radar_score.desc())
                .limit(5).all())
        new_opportunities = [
            {
                "symbol":         st.symbol,
                "name_ar":        st.name_ar,
                "opp_type":       opp.opp_type,
                "entry_price":    opp.entry_price,
                "tp1_price":      opp.tp1_price,
                "sl_price":       opp.sl_price,
                "radar_score":    opp.radar_score,
                "signal_quality": opp.signal_quality,
                "run_date":       opp.run_date.isoformat(),
            }
            for opp, st in opps
        ]

    opp_count = (Opportunity.query
                 .filter(Opportunity.outcome == "PENDING",
                         Opportunity.is_active == True,
                         ~Opportunity.opp_type.like("TREND_%"))
                 .count())

    regime_data = None
    if regime_today:
        regime_data = {
            "regime":     regime_today.regime,
            "confidence": regime_today.confidence,
            "run_date":   regime_today.run_date.isoformat(),
            "reason":     {
                "ar": regime_today.reason_ar,
                "en": regime_today.reason_en,
            },
        }

    return jsonify({
        "as_of":               latest_date.isoformat() if latest_date else None,
        "regime":              regime_data,
        "egx30_close":         egx30_close,
        "egx30_change_pct":    egx30_change_pct,
        "breadth":             breadth,
        "top_scores":          top_scores,
        "top_rvol":            top_rvol,
        "new_opportunities":   new_opportunities,
        "opportunities_count": opp_count,
        "scored_count":        scored_count,
    })
