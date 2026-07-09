"""Tests for GET /api/discover — stock screener."""
import pytest
from datetime import date
from app import create_app, db
from app.models.stock import Stock
from app.models.score import RadarScoreHistory
from app.models.opportunity import Opportunity


@pytest.fixture()
def client():
    app = create_app()
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        CACHE_TYPE="SimpleCache",
        JWT_SECRET_KEY="test-secret",
    )
    with app.app_context():
        db.create_all()
        _seed()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def _seed():
    s1 = Stock(symbol="COMI", name_ar="بنك القاهرة", name_en="CIB",
               sector="البنوك", is_sharia=False, is_active=True,
               last_price=90.0, last_change_pct=1.5)
    s2 = Stock(symbol="HRHO", name_ar="هيرمس", name_en="Hermes",
               sector="الخدمات المالية", is_sharia=False, is_active=True,
               last_price=45.0, last_change_pct=-0.8)
    s3 = Stock(symbol="AMOC", name_ar="ألكسندريا للمصافي", name_en="AMOC",
               sector="البتروكيماويات", is_sharia=True, is_active=True,
               last_price=12.0, last_change_pct=0.3)
    s4 = Stock(symbol="INAC", name_ar="غير نشط", name_en="Inactive",
               sector="البنوك", is_sharia=False, is_active=False,
               last_price=5.0, last_change_pct=0.0)
    db.session.add_all([s1, s2, s3, s4])
    db.session.commit()

    today = date.today()
    db.session.add_all([
        RadarScoreHistory(stock_id=s1.id, run_date=today, score=82.0,
                          rsi=55.0, adx=28.0, rvol=1.8, obv_trend="UP",
                          data_quality="HIGH"),
        RadarScoreHistory(stock_id=s2.id, run_date=today, score=61.0,
                          rsi=42.0, adx=18.0, rvol=0.9, obv_trend="FLAT",
                          data_quality="MEDIUM"),
        RadarScoreHistory(stock_id=s3.id, run_date=today, score=74.0,
                          rsi=60.0, adx=22.0, rvol=1.3, obv_trend="UP",
                          data_quality="HIGH"),
    ])

    # Active opportunity on COMI only
    db.session.add(Opportunity(
        stock_id=s1.id, run_date=today,
        opp_type="Breakout",
        entry_price=89.0, tp1_price=95.0, tp2_price=102.0, sl_price=85.0,
        rr_ratio=1.5, radar_score=82.0, signal_quality="HIGH",
        outcome="PENDING", is_active=True,
    ))
    db.session.commit()


# ── Basic response ────────────────────────────────────────────────────────────

class TestDiscoverBasic:
    def test_returns_200(self, client):
        assert client.get("/api/discover").status_code == 200

    def test_response_has_required_keys(self, client):
        data = client.get("/api/discover").get_json()
        for key in ("total", "limit", "offset", "sort", "sectors", "items"):
            assert key in data

    def test_returns_active_stocks_only(self, client):
        data = client.get("/api/discover").get_json()
        symbols = [i["symbol"] for i in data["items"]]
        assert "INAC" not in symbols

    def test_total_matches_active_scored_stocks(self, client):
        data = client.get("/api/discover").get_json()
        assert data["total"] == 3

    def test_default_sort_by_score_desc(self, client):
        data = client.get("/api/discover").get_json()
        scores = [i["score"] for i in data["items"]]
        assert scores == sorted(scores, reverse=True)

    def test_item_has_required_fields(self, client):
        item = client.get("/api/discover").get_json()["items"][0]
        for field in ("symbol", "name_ar", "sector", "is_sharia", "score",
                      "run_date", "data_quality", "last_price", "last_change_pct",
                      "rsi", "adx", "rvol", "obv_trend", "has_opportunity", "opp_type"):
            assert field in item

    def test_sectors_list_populated(self, client):
        data = client.get("/api/discover").get_json()
        assert len(data["sectors"]) >= 3


# ── Filters ───────────────────────────────────────────────────────────────────

class TestDiscoverFilters:
    def test_filter_by_sector(self, client):
        data = client.get("/api/discover?sector=البنوك").get_json()
        assert all(i["sector"] == "البنوك" for i in data["items"])
        assert data["total"] == 1

    def test_filter_sharia_only(self, client):
        data = client.get("/api/discover?sharia=1").get_json()
        assert all(i["is_sharia"] for i in data["items"])
        assert data["total"] == 1
        assert data["items"][0]["symbol"] == "AMOC"

    def test_filter_min_score(self, client):
        data = client.get("/api/discover?min_score=70").get_json()
        assert all(i["score"] >= 70 for i in data["items"])
        assert data["total"] == 2

    def test_filter_max_score(self, client):
        data = client.get("/api/discover?max_score=70").get_json()
        assert all(i["score"] <= 70 for i in data["items"])
        assert data["total"] == 1

    def test_filter_min_and_max_score(self, client):
        data = client.get("/api/discover?min_score=60&max_score=80").get_json()
        assert all(60 <= i["score"] <= 80 for i in data["items"])

    def test_opp_only_filter(self, client):
        data = client.get("/api/discover?opp_only=1").get_json()
        assert data["total"] == 1
        assert data["items"][0]["symbol"] == "COMI"

    def test_unknown_sector_returns_empty(self, client):
        data = client.get("/api/discover?sector=مجهول").get_json()
        assert data["total"] == 0
        assert data["items"] == []


# ── Sorting ───────────────────────────────────────────────────────────────────

class TestDiscoverSort:
    def test_sort_by_rvol(self, client):
        data = client.get("/api/discover?sort=rvol").get_json()
        rvols = [i["rvol"] for i in data["items"] if i["rvol"] is not None]
        assert rvols == sorted(rvols, reverse=True)

    def test_sort_by_rsi(self, client):
        data = client.get("/api/discover?sort=rsi").get_json()
        rsis = [i["rsi"] for i in data["items"] if i["rsi"] is not None]
        assert rsis == sorted(rsis, reverse=True)

    def test_invalid_sort_falls_back_to_score(self, client):
        data = client.get("/api/discover?sort=invalid").get_json()
        assert data["sort"] == "score"


# ── Pagination ────────────────────────────────────────────────────────────────

class TestDiscoverPagination:
    def test_limit_param(self, client):
        data = client.get("/api/discover?limit=2").get_json()
        assert len(data["items"]) == 2
        assert data["limit"] == 2

    def test_offset_param(self, client):
        data = client.get("/api/discover?limit=2&offset=2").get_json()
        assert len(data["items"]) == 1

    def test_total_unaffected_by_pagination(self, client):
        data = client.get("/api/discover?limit=1").get_json()
        assert data["total"] == 3


# ── Opportunity enrichment ────────────────────────────────────────────────────

class TestDiscoverOpportunity:
    def test_comi_has_opportunity(self, client):
        data = client.get("/api/discover").get_json()
        comi = next(i for i in data["items"] if i["symbol"] == "COMI")
        assert comi["has_opportunity"] is True
        assert comi["opp_type"] == "Breakout"

    def test_hrho_no_opportunity(self, client):
        data = client.get("/api/discover").get_json()
        hrho = next(i for i in data["items"] if i["symbol"] == "HRHO")
        assert hrho["has_opportunity"] is False
        assert hrho["opp_type"] is None
