"""Unit tests for POST /api/analytics/events."""
import json
import pytest

from app import create_app, db


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def _post(client, events):
    return client.post(
        "/api/analytics/events",
        data=json.dumps({"events": events}),
        content_type="application/json",
    )


class TestAnalyticsIngest:
    def test_empty_batch_returns_204(self, client):
        resp = _post(client, [])
        assert resp.status_code == 204

    def test_valid_event_returns_204(self, client):
        resp = _post(client, [{"name": "page_view", "props": {"path": "/"}, "ts": 1000}])
        assert resp.status_code == 204

    def test_unknown_event_silently_skipped(self, client):
        resp = _post(client, [{"name": "hacker_event", "props": {}}])
        assert resp.status_code == 204

    def test_mixed_known_unknown_events(self, client):
        events = [
            {"name": "page_view",    "props": {"path": "/"},        "ts": 1},
            {"name": "bad_event",    "props": {},                   "ts": 2},
            {"name": "regime_viewed","props": {"regime": "BULL"},   "ts": 3},
        ]
        resp = _post(client, events)
        assert resp.status_code == 204

    def test_stock_page_viewed_denormalizes_symbol(self, client):
        from app.models.analytics import AnalyticsEvent
        _post(client, [{"name": "stock_page_viewed", "props": {"symbol": "COMI"}, "ts": 5}])
        with client.application.app_context():
            row = db.session.query(AnalyticsEvent).filter_by(name="stock_page_viewed").first()
            assert row is not None
            assert row.symbol == "COMI"

    def test_widget_viewed_denormalizes_widget_id(self, client):
        from app.models.analytics import AnalyticsEvent
        _post(client, [{"name": "widget_viewed", "props": {"widget_id": "WGT-002"}, "ts": 6}])
        with client.application.app_context():
            row = db.session.query(AnalyticsEvent).filter_by(name="widget_viewed").first()
            assert row is not None
            assert row.widget_id == "WGT-002"

    def test_page_view_denormalizes_path(self, client):
        from app.models.analytics import AnalyticsEvent
        _post(client, [{"name": "page_view", "props": {"path": "/stocks/COMI"}, "ts": 7}])
        with client.application.app_context():
            row = db.session.query(AnalyticsEvent).filter_by(name="page_view", ts=7).first()
            assert row is not None
            assert row.path == "/stocks/COMI"

    def test_batch_cap_at_50(self, client):
        from app.models.analytics import AnalyticsEvent
        events = [{"name": "page_view", "props": {"path": "/"}, "ts": i} for i in range(60)]
        _post(client, events)
        with client.application.app_context():
            count = db.session.query(AnalyticsEvent).count()
            assert count == 50

    def test_missing_events_key_returns_204(self, client):
        resp = client.post(
            "/api/analytics/events",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 204

    def test_events_not_array_returns_400(self, client):
        resp = client.post(
            "/api/analytics/events",
            data=json.dumps({"events": "not-a-list"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_all_allowed_event_names_accepted(self, client):
        allowed = [
            "page_view", "search_performed", "opportunity_clicked",
            "regime_viewed", "sharia_filter_toggled", "stock_page_viewed",
            "score_gauge_viewed", "explain_viewed", "opportunity_card_viewed",
            "error_shown", "retry_clicked", "widget_viewed",
        ]
        events = [{"name": n, "props": {}, "ts": i} for i, n in enumerate(allowed)]
        resp = _post(client, events)
        assert resp.status_code == 204
