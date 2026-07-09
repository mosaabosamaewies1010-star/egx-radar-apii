"""
POST /api/analytics/events — ingest batched frontend events.
Lightweight: validates schema, persists to DB, returns 204.
"""
from flask import Blueprint, request, jsonify
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
