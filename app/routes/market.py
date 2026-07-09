"""
/api/market/regime   — current market regime
/api/market/summary  — full market snapshot (indices + breadth + sector ranking)
/api/market/heatmap  — all scored stocks for visual heatmap
"""
from flask import Blueprint, jsonify
from sqlalchemy import func

from app import db, cache
from app.models.regime import MarketRegimeHistory
from app.models.score import RadarScoreHistory
from app.models.stock import Stock
from app.models.opportunity import Opportunity
from app.services.market_regime import compute_market_regime

market_bp = Blueprint("market", __name__)


@market_bp.get("/api/market/regime")
@cache.cached(timeout=600, key_prefix="market_regime")
def get_regime():
    # Return latest from DB first
    latest = (MarketRegimeHistory.query
              .order_by(MarketRegimeHistory.run_date.desc())
              .first())

    if latest:
        return jsonify(latest.to_dict())

    # Live compute if no record
    result = compute_market_regime()
    if result is None:
        return jsonify({"regime": "SIDEWAYS", "confidence": 50,
                        "reason": {"ar": "بيانات غير متاحة", "en": "Data unavailable"}}), 200

    return jsonify({
        "regime":     result.regime,
        "confidence": result.confidence,
        "breadth": {
            "advancing": result.advancing,
            "declining": result.declining,
            "unchanged": result.unchanged,
        },
        "scores": {
            "ma":         result.ma_score,
            "breadth":    result.breadth_score,
            "adx":        result.adx_score,
            "volatility": result.volatility_score,
            "volume":     result.volume_score,
        },
        "egx30": {
            "close": result.egx30_close,
            "ma20":  result.egx30_ma20,
            "ma50":  result.egx30_ma50,
            "ma200": result.egx30_ma200,
        },
        "reason": {
            "ar": result.reason_ar,
            "en": result.reason_en,
        },
    })


@market_bp.get("/api/market/summary")
@cache.cached(timeout=300, key_prefix="market_summary")
def get_market_summary():
    """Full market snapshot: regime + EGX30 change + sector ranking + top stocks."""
    # Latest two regime records for EGX30 change %
    regimes = (MarketRegimeHistory.query
               .order_by(MarketRegimeHistory.run_date.desc())
               .limit(2).all())

    regime_today = regimes[0] if regimes else None
    regime_prev  = regimes[1] if len(regimes) > 1 else None

    egx30_close      = regime_today.egx30_close if regime_today else None
    egx30_change_pct = None
    if regime_today and regime_prev and regime_today.egx30_close and regime_prev.egx30_close:
        egx30_change_pct = round(
            (regime_today.egx30_close - regime_prev.egx30_close) / regime_prev.egx30_close * 100, 2
        )

    # Latest date with scored stocks
    latest_date = db.session.query(func.max(RadarScoreHistory.run_date)).scalar()

    sector_ranking: list = []
    top_volume:     list = []
    top_breakouts:  list = []

    if latest_date:
        rows = (db.session.query(RadarScoreHistory, Stock)
                .join(Stock, RadarScoreHistory.stock_id == Stock.id)
                .filter(RadarScoreHistory.run_date == latest_date)
                .all())

        # Sector aggregation
        sector_agg: dict = {}
        for score_row, stock in rows:
            sector = stock.sector or "غير محدد"
            bucket = sector_agg.setdefault(sector, {"total": 0.0, "count": 0})
            bucket["total"] += score_row.score
            bucket["count"] += 1

        sector_ranking = sorted(
            [
                {"sector": s, "avg_score": round(v["total"] / v["count"], 1), "count": v["count"]}
                for s, v in sector_agg.items()
            ],
            key=lambda x: -x["avg_score"],
        )

        # Top 5 by RVOL
        vol_sorted = sorted(rows, key=lambda r: r[0].rvol or 0, reverse=True)[:5]
        top_volume = [
            {"symbol": st.symbol, "name_ar": st.name_ar,
             "rvol": round(sc.rvol or 0, 1), "score": round(sc.score, 1)}
            for sc, st in vol_sorted
        ]

        # Top 5 breakouts: score >= 60, sorted by trend_score
        breakouts = [(sc, st) for sc, st in rows if sc.score >= 60]
        breakouts.sort(key=lambda x: x[0].trend_score or 0, reverse=True)
        top_breakouts = [
            {"symbol": st.symbol, "name_ar": st.name_ar,
             "score": round(sc.score, 1), "trend_score": round(sc.trend_score or 0, 1)}
            for sc, st in breakouts[:5]
        ]

    # Active opportunities count (no outcome yet)
    opp_count = Opportunity.query.filter(Opportunity.outcome.is_(None)).count()

    return jsonify({
        "as_of":               latest_date.isoformat() if latest_date else None,
        "regime":              regime_today.to_dict() if regime_today else None,
        "egx30_close":         egx30_close,
        "egx30_change_pct":    egx30_change_pct,
        "sector_ranking":      sector_ranking,
        "top_volume":          top_volume,
        "top_breakouts":       top_breakouts,
        "opportunities_count": opp_count,
    })


@market_bp.get("/api/market/heatmap")
@cache.cached(timeout=300, key_prefix="market_heatmap")
def get_heatmap():
    """All scored stocks for the visual heatmap, grouped by sector."""
    latest_date = db.session.query(func.max(RadarScoreHistory.run_date)).scalar()
    if not latest_date:
        return jsonify({"stocks": [], "as_of": None})

    rows = (db.session.query(RadarScoreHistory, Stock)
            .join(Stock, RadarScoreHistory.stock_id == Stock.id)
            .filter(RadarScoreHistory.run_date == latest_date)
            .order_by(Stock.sector, RadarScoreHistory.score.desc())
            .all())

    stocks = [
        {
            "symbol":     st.symbol,
            "name_ar":    st.name_ar,
            "sector":     st.sector or "غير محدد",
            "score":      round(sc.score, 1),
            "change_pct": st.last_change_pct or 0,
        }
        for sc, st in rows
    ]

    return jsonify({"stocks": stocks, "as_of": latest_date.isoformat()})
