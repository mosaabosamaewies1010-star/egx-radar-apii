"""Tests for POST /api/bot/signal and POST /api/bot/outcome."""
import os
import pytest
from datetime import date, datetime, timezone

from app import create_app, db
from app.models import Stock, Opportunity, StrategyVersion

BOT_KEY = "test-bot-key-123"
HEADERS = {"X-Bot-Api-Key": BOT_KEY, "Content-Type": "application/json"}

VALID_SIGNAL = {
    "symbol":      "COMI",
    "entry_price": 10.0,
    "tp1_price":   11.0,
    "tp2_price":   12.0,
    "sl_price":    9.5,
    "opp_type":    "Breakout",
    "radar_score": 78.5,
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("BOT_API_KEY", BOT_KEY)
    application = create_app("testing")
    application.config["TESTING"] = True
    application.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def version(app):
    with app.app_context():
        ver = StrategyVersion(version="live_v1", effective_from=date(2024, 1, 1))
        db.session.add(ver)
        db.session.commit()
        return ver.id


# ── Auth ──────────────────────────────────────────────────────────────────────

class TestBotAuth:
    def test_signal_no_key_returns_401(self, client):
        res = client.post("/api/bot/signal", json=VALID_SIGNAL)
        assert res.status_code == 401

    def test_signal_wrong_key_returns_401(self, client):
        res = client.post("/api/bot/signal", json=VALID_SIGNAL,
                          headers={"X-Bot-Api-Key": "wrong-key"})
        assert res.status_code == 401

    def test_outcome_no_key_returns_401(self, client):
        res = client.post("/api/bot/outcome", json={"opp_id": 1, "outcome": "WIN"})
        assert res.status_code == 401


# ── Signal creation ───────────────────────────────────────────────────────────

class TestBotSignal:
    def test_valid_signal_returns_201(self, client):
        res = client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS)
        assert res.status_code == 201

    def test_valid_signal_returns_id(self, client):
        data = client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS).get_json()
        assert "id" in data
        assert isinstance(data["id"], int)

    def test_valid_signal_status_created(self, client):
        data = client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS).get_json()
        assert data["status"] == "created"

    def test_creates_stock_if_missing(self, client, app):
        client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS)
        with app.app_context():
            assert Stock.query.filter_by(symbol="COMI").first() is not None

    def test_creates_opportunity_pending(self, client, app):
        client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS)
        with app.app_context():
            opp = Opportunity.query.first()
            assert opp.outcome == "PENDING"

    def test_links_strategy_version(self, client, app, version):
        client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS)
        with app.app_context():
            opp = Opportunity.query.first()
            assert opp.strategy_version_id == version

    def test_stores_feature_snapshot(self, client, app):
        payload = {**VALID_SIGNAL, "feature_snapshot": {"rsi": 62.5, "adx": 30.1}}
        client.post("/api/bot/signal", json=payload, headers=HEADERS)
        with app.app_context():
            opp = Opportunity.query.first()
            assert opp.feature_snapshot["rsi"] == pytest.approx(62.5)

    def test_computes_rr_ratio(self, client, app):
        client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS)
        with app.app_context():
            opp = Opportunity.query.first()
            # rr = (11 - 10) / (10 - 9.5) = 2.0
            assert opp.rr_ratio == pytest.approx(2.0)

    def test_custom_signal_date(self, client, app):
        payload = {**VALID_SIGNAL, "signal_date": "2024-03-15"}
        client.post("/api/bot/signal", json=payload, headers=HEADERS)
        with app.app_context():
            opp = Opportunity.query.first()
            assert opp.run_date == date(2024, 3, 15)

    def test_missing_required_field_returns_400(self, client):
        bad = {k: v for k, v in VALID_SIGNAL.items() if k != "tp1_price"}
        res = client.post("/api/bot/signal", json=bad, headers=HEADERS)
        assert res.status_code == 400

    def test_invalid_levels_returns_400(self, client):
        bad = {**VALID_SIGNAL, "tp1_price": 9.0}   # tp1 < entry — invalid
        res = client.post("/api/bot/signal", json=bad, headers=HEADERS)
        assert res.status_code == 400

    def test_idempotency_duplicate_returns_200(self, client):
        client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS)
        res = client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS)
        assert res.status_code == 200
        assert res.get_json()["status"] == "duplicate"

    def test_idempotency_does_not_create_second_row(self, client, app):
        client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS)
        client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS)
        with app.app_context():
            assert Opportunity.query.count() == 1

    def test_reuses_existing_stock(self, client, app):
        client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS)
        client.post("/api/bot/signal",
                    json={**VALID_SIGNAL, "entry_price": 10.5, "tp1_price": 11.5, "tp2_price": 12.5},
                    headers=HEADERS)
        with app.app_context():
            assert Stock.query.filter_by(symbol="COMI").count() == 1
            assert Opportunity.query.count() == 2


# ── Outcome update ────────────────────────────────────────────────────────────

class TestBotOutcome:
    def _create_opp(self, client):
        return client.post("/api/bot/signal", json=VALID_SIGNAL, headers=HEADERS).get_json()["id"]

    def test_win_outcome_200(self, client):
        opp_id = self._create_opp(client)
        res = client.post("/api/bot/outcome",
                          json={"opp_id": opp_id, "outcome": "WIN",
                                "exit_reason": "TP1", "exit_price": 11.0},
                          headers=HEADERS)
        assert res.status_code == 200

    def test_win_pnl_computed(self, client, app):
        opp_id = self._create_opp(client)
        client.post("/api/bot/outcome",
                    json={"opp_id": opp_id, "outcome": "WIN",
                          "exit_reason": "TP1", "exit_price": 11.0},
                    headers=HEADERS)
        with app.app_context():
            opp = Opportunity.query.get(opp_id)
            assert opp.pnl_pct == pytest.approx(10.0)   # (11 - 10) / 10 * 100

    def test_loss_pnl_negative(self, client, app):
        opp_id = self._create_opp(client)
        client.post("/api/bot/outcome",
                    json={"opp_id": opp_id, "outcome": "LOSS",
                          "exit_reason": "SL", "exit_price": 9.5},
                    headers=HEADERS)
        with app.app_context():
            opp = Opportunity.query.get(opp_id)
            assert opp.pnl_pct == pytest.approx(-5.0)   # (9.5 - 10) / 10 * 100

    def test_outcome_sets_closed_at(self, client, app):
        opp_id = self._create_opp(client)
        client.post("/api/bot/outcome",
                    json={"opp_id": opp_id, "outcome": "EXPIRED",
                          "closed_date": "2024-06-01"},
                    headers=HEADERS)
        with app.app_context():
            opp = Opportunity.query.get(opp_id)
            assert opp.closed_at == date(2024, 6, 1)

    def test_not_found_returns_404(self, client):
        res = client.post("/api/bot/outcome",
                          json={"opp_id": 9999, "outcome": "WIN"},
                          headers=HEADERS)
        assert res.status_code == 404

    def test_invalid_outcome_returns_400(self, client):
        opp_id = self._create_opp(client)
        res = client.post("/api/bot/outcome",
                          json={"opp_id": opp_id, "outcome": "MAYBE"},
                          headers=HEADERS)
        assert res.status_code == 400

    def test_missing_opp_id_returns_400(self, client):
        res = client.post("/api/bot/outcome",
                          json={"outcome": "WIN"}, headers=HEADERS)
        assert res.status_code == 400
