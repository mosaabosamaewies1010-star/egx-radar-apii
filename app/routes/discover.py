"""
/api/discover — Stock screener ranked by latest Radar Score.
Returns one row per stock (most-recent score), with optional filters.
"""
from flask import Blueprint, jsonify, request
from sqlalchemy import func

from app import db, cache
from app.models.stock import Stock
from app.models.score import RadarScoreHistory
from app.models.opportunity import Opportunity

discover_bp = Blueprint("discover", __name__)

VALID_SORT = {"score", "rvol", "rsi", "change_pct"}


@discover_bp.get("/api/discover")
@cache.cached(timeout=180, key_prefix=lambda: f"discover_{request.query_string.decode()}")
def discover():
    # ── query params ──────────────────────────────────────────────────────────
    sector      = (request.args.get("sector") or "").strip() or None
    sharia_only = request.args.get("sharia") == "1"
    min_score   = request.args.get("min_score", type=float)
    max_score   = request.args.get("max_score", type=float)
    opp_only    = request.args.get("opp_only") == "1"
    sort_by     = request.args.get("sort", "score")
    if sort_by not in VALID_SORT:
        sort_by = "score"
    limit  = min(int(request.args.get("limit",  30)), 100)
    offset = int(request.args.get("offset", 0))

    # ── latest score per stock (subquery) ─────────────────────────────────────
    latest_date_sub = (
        db.session.query(
            RadarScoreHistory.stock_id,
            func.max(RadarScoreHistory.run_date).label("max_date"),
        )
        .group_by(RadarScoreHistory.stock_id)
        .subquery()
    )

    query = (
        db.session.query(RadarScoreHistory, Stock)
        .join(Stock, RadarScoreHistory.stock_id == Stock.id)
        .join(
            latest_date_sub,
            (RadarScoreHistory.stock_id == latest_date_sub.c.stock_id)
            & (RadarScoreHistory.run_date == latest_date_sub.c.max_date),
        )
        .filter(Stock.is_active == True)
    )

    # ── filters ───────────────────────────────────────────────────────────────
    if sector:
        query = query.filter(Stock.sector == sector)
    if sharia_only:
        query = query.filter(Stock.is_sharia == True)
    if min_score is not None:
        query = query.filter(RadarScoreHistory.score >= min_score)
    if max_score is not None:
        query = query.filter(RadarScoreHistory.score <= max_score)

    # ── optional: only stocks with active opportunity ─────────────────────────
    if opp_only:
        active_stock_ids_q = (
            db.session.query(Opportunity.stock_id)
            .filter(Opportunity.outcome == "PENDING", Opportunity.is_active == True)
        )
        query = query.filter(Stock.id.in_(active_stock_ids_q))

    # ── sort ──────────────────────────────────────────────────────────────────
    if sort_by == "score":
        query = query.order_by(RadarScoreHistory.score.desc())
    elif sort_by == "rvol":
        query = query.order_by(RadarScoreHistory.rvol.desc().nulls_last())
    elif sort_by == "rsi":
        query = query.order_by(RadarScoreHistory.rsi.desc().nulls_last())
    elif sort_by == "change_pct":
        query = query.order_by(Stock.last_change_pct.desc().nulls_last())

    total = query.count()
    rows  = query.offset(offset).limit(limit).all()

    # ── build active-opp lookup ───────────────────────────────────────────────
    stock_ids = [stock.id for _, stock in rows]
    active_opps = {}
    if stock_ids:
        opps = (
            Opportunity.query
            .filter(
                Opportunity.stock_id.in_(stock_ids),
                Opportunity.outcome == "PENDING",
                Opportunity.is_active == True,
            )
            .all()
        )
        for o in opps:
            active_opps[o.stock_id] = o.opp_type

    # ── serialize ─────────────────────────────────────────────────────────────
    items = []
    for score_row, stock in rows:
        opp_type = active_opps.get(stock.id)
        items.append({
            "symbol":          stock.symbol,
            "name_ar":         stock.name_ar,
            "sector":          stock.sector,
            "is_sharia":       stock.is_sharia,
            "score":           round(score_row.score, 1),
            "run_date":        score_row.run_date.isoformat(),
            "data_quality":    score_row.data_quality,
            "last_price":      stock.last_price,
            "last_change_pct": stock.last_change_pct,
            "rsi":             round(score_row.rsi, 1) if score_row.rsi else None,
            "adx":             round(score_row.adx, 1) if score_row.adx else None,
            "rvol":            round(score_row.rvol, 2) if score_row.rvol else None,
            "obv_trend":       score_row.obv_trend,
            "has_opportunity": opp_type is not None,
            "opp_type":        opp_type,
        })

    # ── available sectors for filter UI ──────────────────────────────────────
    sectors = [
        r[0] for r in
        db.session.query(Stock.sector).filter(Stock.sector != None, Stock.is_active == True)
        .distinct().order_by(Stock.sector).all()
    ]

    return jsonify({
        "total":   total,
        "limit":   limit,
        "offset":  offset,
        "sort":    sort_by,
        "sectors": sectors,
        "items":   items,
    })
