"""
POST /api/analytics/events — ingest batched frontend events.
GET  /api/analytics/summary — beta telemetry summary for admin dashboard.
"""
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify
from sqlalchemy import func
from app import db
from app.models.analytics import AnalyticsEvent

analytics_bp = Blueprint("analytics", __name__)

# Events we accept — any unknown name is silently ignored
ALLOWED_EVENTS = {
    "page_view", "search_performed",
    "opportunity_clicked", "regime_viewed", "sharia_filter_toggled",
    "stock_page_viewed", "score_gauge_viewed", "explain_viewed",
    "opportunity_card_viewed", "error_shown", "retry_clicked",
    "widget_viewed",
    "pro_upgrade_clicked", "discover_opened", "watchlist_added",
    "morning_brief_opened", "stock_searched",
}

MAX_BATCH = 50   # cap per request


@analytics_bp.post("/api/analytics/events")
def ingest_events():
    body = request.get_json(silent=True) or {}
    events = body.get("events", [])

    if not isinstance(events, list):
        return jsonify({"error": "events must be an array"}), 400

    rows = []
    for ev in events[:MAX_BATCH]:
        name = ev.get("name", "")
        if name not in ALLOWED_EVENTS:
            continue

        props = ev.get("props", {}) or {}
        rows.append(AnalyticsEvent(
            name=name,
            props=props,
            ts=ev.get("ts"),
            symbol=props.get("symbol"),
            path=props.get("path"),
            widget_id=props.get("widget_id"),
        ))

    if rows:
        db.session.bulk_save_objects(rows)
        db.session.commit()

    return "", 204


@analytics_bp.get("/api/analytics/summary")
def analytics_summary():
    """Beta telemetry summary — last 7 and 30 days."""
    now      = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    def count_event(name, since):
        return db.session.query(func.count(AnalyticsEvent.id)).filter(
            AnalyticsEvent.name == name,
            AnalyticsEvent.received_at >= since,
        ).scalar() or 0

    def top_symbols(since, limit=10):
        rows = (
            db.session.query(AnalyticsEvent.symbol, func.count(AnalyticsEvent.id).label("n"))
            .filter(AnalyticsEvent.name == "stock_page_viewed", AnalyticsEvent.symbol.isnot(None), AnalyticsEvent.received_at >= since)
            .group_by(AnalyticsEvent.symbol)
            .order_by(func.count(AnalyticsEvent.id).desc())
            .limit(limit)
            .all()
        )
        return [{"symbol": r.symbol, "views": r.n} for r in rows]

    return jsonify({
        "7d": {
            "stock_views":        count_event("stock_page_viewed", week_ago),
            "discover_opens":     count_event("discover_opened", week_ago),
            "pro_upgrade_clicks": count_event("pro_upgrade_clicked", week_ago),
            "searches":           count_event("stock_searched", week_ago),
            "watchlist_adds":     count_event("watchlist_added", week_ago),
        },
        "30d": {
            "stock_views":        count_event("stock_page_viewed", month_ago),
            "discover_opens":     count_event("discover_opened", month_ago),
            "pro_upgrade_clicks": count_event("pro_upgrade_clicked", month_ago),
            "searches":           count_event("stock_searched", month_ago),
            "watchlist_adds":     count_event("watchlist_added", month_ago),
        },
        "top_symbols_7d": top_symbols(week_ago),
    })
