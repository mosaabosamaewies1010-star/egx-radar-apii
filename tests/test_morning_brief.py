"""Tests for GET /api/morning-brief."""
import pytest
from datetime import date
from app import create_app, db
from app.models.stock import Stock
from app.models.score import RadarScoreHistory
from app.models.regime import MarketRegimeHistory
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


@pytest.fixture()
def empty_client():
    """Client with no data at all."""
    app = create_app()
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        CACHE_TYPE="SimpleCache",
        JWT_SECRET_KEY="test-secret",
    )
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


TODAY = date.today()


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
    db.session.add_all([s1, s2, s3])
    db.session.commit()

    db.session.add_all([
        RadarScoreHistory(stock_id=s1.id, run_date=TODAY, score=82.0,
                          rvol=1.8, data_quality="HIGH"),
        RadarScoreHistory(stock_id=s2.id, run_date=TODAY, score=61.0,
                          rvol=0.9, data_quality="MEDIUM"),
        RadarScoreHistory(stock_id=s3.id, run_date=TODAY, score=74.0,
                          rvol=1.3, data_quality="HIGH"),
    ])
    db.session.commit()

    db.session.add(MarketRegimeHistory(
        run_date=TODAY, regime="BULL", confidence=75.0,
        advancing=45, declining=12, unchanged=8,
        egx30_close=31500.0,
        reason_ar="السوق صاعد", reason_en="Bullish market",
    ))
    db.session.commit()

    db.session.add(Opportunity(
        stock_id=s1.id, run_date=TODAY,
        opp_type="Breakout",
        entry_price=89.0, tp1_price=95.0, tp2_price=102.0, sl_price=85.0,
        rr_ratio=1.5, radar_score=82.0, signal_quality="HIGH",
        outcome="PENDING", is_active=True,
    ))
    db.session.commit()


# ── Status & shape ────────────────────────────────────────────────────────────

def test_morning_brief_200(client):
    r = client.get("/api/morning-brief")
    assert r.status_code == 200


def test_morning_brief_shape(client):
    data = client.get("/api/morning-brief").get_json()
    for key in ("as_of", "regime", "egx30_close", "egx30_change_pct",
                "breadth", "top_scores", "top_rvol",
                "new_opportunities", "opportunities_count", "scored_count"):
        assert key in data, f"missing key: {key}"


def test_morning_brief_empty_db_200(empty_client):
    r = empty_client.get("/api/morning-brief")
    assert r.status_code == 200


def test_morning_brief_empty_db_defaults(empty_client):
    data = empty_client.get("/api/morning-brief").get_json()
    assert data["as_of"] is None
    assert data["regime"] is None
    assert data["top_scores"] == []
    assert data["top_rvol"] == []
    assert data["new_opportunities"] == []


# ── as_of ─────────────────────────────────────────────────────────────────────

def test_as_of_is_latest_date(client):
    data = client.get("/api/morning-brief").get_json()
    assert data["as_of"] == TODAY.isoformat()


# ── Regime ────────────────────────────────────────────────────────────────────

def test_regime_included(client):
    data = client.get("/api/morning-brief").get_json()
    assert data["regime"] is not None
    assert data["regime"]["regime"] == "BULL"


def test_regime_has_confidence(client):
    data = client.get("/api/morning-brief").get_json()
    assert "confidence" in data["regime"]


def test_regime_has_reason(client):
    data = client.get("/api/morning-brief").get_json()
    assert "reason" in data["regime"]
    assert "ar" in data["regime"]["reason"]


# ── Breadth ───────────────────────────────────────────────────────────────────

def test_breadth_included(client):
    data = client.get("/api/morning-brief").get_json()
    assert data["breadth"] is not None
    assert data["breadth"]["advancing"] == 45
    assert data["breadth"]["declining"] == 12


# ── EGX30 ─────────────────────────────────────────────────────────────────────

def test_egx30_close_included(client):
    data = client.get("/api/morning-brief").get_json()
    assert data["egx30_close"] == 31500.0


def test_egx30_change_pct_none_with_single_regime(client):
    # Only one regime row seeded → change cannot be computed
    data = client.get("/api/morning-brief").get_json()
    assert data["egx30_change_pct"] is None


# ── Top scores ────────────────────────────────────────────────────────────────

def test_top_scores_count(client):
    data = client.get("/api/morning-brief").get_json()
    assert len(data["top_scores"]) == 3   # 3 stocks seeded


def test_top_scores_sorted_desc(client):
    data = client.get("/api/morning-brief").get_json()
    scores = [s["score"] for s in data["top_scores"]]
    assert scores == sorted(scores, reverse=True)


def test_top_scores_item_shape(client):
    data = client.get("/api/morning-brief").get_json()
    item = data["top_scores"][0]
    for key in ("symbol", "name_ar", "sector", "is_sharia", "score", "last_change_pct"):
        assert key in item


def test_top_scores_max_5(client):
    data = client.get("/api/morning-brief").get_json()
    assert len(data["top_scores"]) <= 5


# ── Top RVOL ─────────────────────────────────────────────────────────────────

def test_top_rvol_count(client):
    data = client.get("/api/morning-brief").get_json()
    assert len(data["top_rvol"]) == 3


def test_top_rvol_sorted_desc(client):
    data = client.get("/api/morning-brief").get_json()
    rvols = [s["rvol"] for s in data["top_rvol"]]
    assert rvols == sorted(rvols, reverse=True)


def test_top_rvol_item_shape(client):
    data = client.get("/api/morning-brief").get_json()
    item = data["top_rvol"][0]
    for key in ("symbol", "name_ar", "rvol", "score"):
        assert key in item


# ── New opportunities ─────────────────────────────────────────────────────────

def test_new_opportunities_included(client):
    data = client.get("/api/morning-brief").get_json()
    assert len(data["new_opportunities"]) == 1


def test_new_opportunity_shape(client):
    data = client.get("/api/morning-brief").get_json()
    opp = data["new_opportunities"][0]
    for key in ("symbol", "name_ar", "opp_type", "entry_price",
                "tp1_price", "sl_price", "radar_score", "signal_quality", "run_date"):
        assert key in opp


def test_opportunities_count(client):
    data = client.get("/api/morning-brief").get_json()
    assert data["opportunities_count"] == 1


# ── scored_count ──────────────────────────────────────────────────────────────

def test_scored_count(client):
    data = client.get("/api/morning-brief").get_json()
    assert data["scored_count"] == 3
