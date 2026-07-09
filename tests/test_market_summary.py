"""Tests for GET /api/market/summary and GET /api/market/heatmap."""
import json
from datetime import date, timedelta
import pytest

from app import create_app, db
from app.models.regime import MarketRegimeHistory
from app.models.stock import Stock
from app.models.score import RadarScoreHistory
from app.models.opportunity import Opportunity


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["CACHE_TYPE"] = "SimpleCache"
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


class TestMarketSummary:
    def test_returns_200(self, client):
        resp = client.get("/api/market/summary")
        assert resp.status_code == 200

    def test_empty_db_returns_nulls(self, client):
        data = client.get("/api/market/summary").get_json()
        assert data["as_of"] is None
        assert data["regime"] is None
        assert data["sector_ranking"] == []
        assert data["top_volume"] == []
        assert data["top_breakouts"] == []
        assert data["opportunities_count"] == 0

    def test_with_seeded_data(self, client):
        with client.application.app_context():
            _seed_ctx()
        data = client.get("/api/market/summary").get_json()
        assert data["regime"]["regime"] == "BULL"
        assert data["regime"]["confidence"] == 78

    def test_egx30_close_present(self, client):
        with client.application.app_context():
            _seed_ctx()
        data = client.get("/api/market/summary").get_json()
        assert data["egx30_close"] == pytest.approx(30360.0)

    def test_egx30_change_pct_computed(self, client):
        with client.application.app_context():
            _seed_ctx()
        data = client.get("/api/market/summary").get_json()
        # (30360 - 30000) / 30000 * 100 = 1.2%
        assert data["egx30_change_pct"] == pytest.approx(1.2, abs=0.01)

    def test_sector_ranking_present(self, client):
        with client.application.app_context():
            _seed_ctx()
        data = client.get("/api/market/summary").get_json()
        assert len(data["sector_ranking"]) == 1
        assert data["sector_ranking"][0]["sector"] == "البنوك"
        assert data["sector_ranking"][0]["avg_score"] == pytest.approx(87.0, abs=0.1)

    def test_top_volume_present(self, client):
        with client.application.app_context():
            _seed_ctx()
        data = client.get("/api/market/summary").get_json()
        assert len(data["top_volume"]) == 1
        assert data["top_volume"][0]["symbol"] == "COMI"

    def test_top_breakouts_only_high_score(self, client):
        with client.application.app_context():
            _seed_ctx()
        data = client.get("/api/market/summary").get_json()
        # COMI has score 87 >= 60, should appear
        assert any(s["symbol"] == "COMI" for s in data["top_breakouts"])

    def test_opportunities_count(self, client):
        with client.application.app_context():
            _seed_ctx()
        data = client.get("/api/market/summary").get_json()
        assert data["opportunities_count"] == 1

    def test_as_of_date_matches_latest_score(self, client):
        with client.application.app_context():
            _seed_ctx()
        data = client.get("/api/market/summary").get_json()
        assert data["as_of"] == date.today().isoformat()


def _seed_ctx():
    """Seed inside an already-active app context."""
    today = date.today()
    yesterday = today - timedelta(days=1)

    stock = Stock(
        symbol="COMI", name_ar="بنك القاهرة", name_en="CIB",
        sector="البنوك", is_sharia=False,
        last_price=87.5, last_change_pct=1.2, last_adt=50_000_000,
    )
    db.session.add(stock)
    db.session.flush()

    db.session.add_all([
        MarketRegimeHistory(
            run_date=yesterday, regime="SIDEWAYS", confidence=55,
            advancing=10, declining=8, unchanged=4,
            egx30_close=30000.0,
        ),
        MarketRegimeHistory(
            run_date=today, regime="BULL", confidence=78,
            advancing=18, declining=7, unchanged=5,
            egx30_close=30360.0,
        ),
    ])
    db.session.flush()

    score = RadarScoreHistory(
        stock_id=stock.id, run_date=today, score=87.0,
        trend_score=17, momentum_score=15, liquidity_score=12,
        volume_score=11, sector_score=9, fundamental_score=10,
        risk_penalty=4, rvol=2.3, adx=32.0, rsi=62.0, atr_pct=1.8,
        obv_trend="UP", data_quality="HIGH",
    )
    db.session.add(score)
    db.session.flush()

    db.session.add(Opportunity(
        stock_id=stock.id, run_date=today,
        opp_type="Breakout", radar_score=87,
        signal_quality="HIGH",
        entry_price=87.5, tp1_price=93.0, tp2_price=98.0,
        sl_price=84.2, rr_ratio=2.1, max_hold_days=10,
    ))
    db.session.commit()


class TestMarketHeatmap:
    def test_returns_200(self, client):
        assert client.get("/api/market/heatmap").status_code == 200

    def test_empty_db_returns_empty_stocks(self, client):
        data = client.get("/api/market/heatmap").get_json()
        assert data["stocks"] == []
        assert data["as_of"] is None

    def test_returns_stock_with_sector(self, client):
        with client.application.app_context():
            _seed_ctx()
        data = client.get("/api/market/heatmap").get_json()
        assert len(data["stocks"]) == 1
        s = data["stocks"][0]
        assert s["symbol"] == "COMI"
        assert s["sector"] == "البنوك"
        assert s["score"] == pytest.approx(87.0, abs=0.1)

    def test_as_of_matches_today(self, client):
        with client.application.app_context():
            _seed_ctx()
        data = client.get("/api/market/heatmap").get_json()
        assert data["as_of"] == date.today().isoformat()
