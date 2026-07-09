"""Tests for GET /api/my-day."""
import pytest
from datetime import date, datetime, timezone
from app import create_app, db
from app.models.stock import Stock
from app.models.score import RadarScoreHistory
from app.models.portfolio import PortfolioHolding
from app.models.watchlist import Watchlist
from app.models.notification import Notification
from app.models.opportunity import Opportunity


TODAY = date.today()


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


def _seed():
    s1 = Stock(symbol="COMI", name_ar="بنك القاهرة", name_en="CIB",
               sector="البنوك", is_sharia=False, is_active=True,
               last_price=95.0, last_change_pct=1.5)   # last_price > alert_price_above
    s2 = Stock(symbol="HRHO", name_ar="هيرمس", name_en="Hermes",
               sector="الخدمات المالية", is_sharia=False, is_active=True,
               last_price=40.0, last_change_pct=-2.0)   # last_price < alert_price_below
    s3 = Stock(symbol="AMOC", name_ar="ألكسندريا", name_en="AMOC",
               sector="البتروكيماويات", is_sharia=True, is_active=True,
               last_price=12.0, last_change_pct=0.3)
    db.session.add_all([s1, s2, s3])
    db.session.commit()

    # Portfolio: 2 open holdings for anonymous user (user_id=None)
    db.session.add_all([
        PortfolioHolding(
            user_id=None, stock_id=s1.id,
            quantity=100, avg_cost=90.0,   # unrealized = (95-90)*100 = +500
        ),
        PortfolioHolding(
            user_id=None, stock_id=s2.id,
            quantity=50, avg_cost=45.0,    # unrealized = (40-45)*50 = -250
        ),
    ])
    db.session.commit()

    # Watchlist for anonymous user
    db.session.add_all([
        Watchlist(user_id=None, stock_id=s1.id,
                  alert_price_above=90.0, alert_price_below=None),   # triggered (95 > 90)
        Watchlist(user_id=None, stock_id=s2.id,
                  alert_price_above=None, alert_price_below=45.0),   # triggered (40 < 45)
        Watchlist(user_id=None, stock_id=s3.id,
                  alert_price_above=None, alert_price_below=None),   # no alert
    ])
    db.session.commit()

    # 2 unread notifications for anonymous
    db.session.add_all([
        Notification(user_id=None, type="score_change",
                     title_ar="تغير الدرجة", is_read=False),
        Notification(user_id=None, type="new_opportunity",
                     title_ar="فرصة جديدة", is_read=False),
        Notification(user_id=None, type="regime_change",
                     title_ar="تغير النظام", is_read=True),  # read — not counted
    ])
    db.session.commit()

    # Active opportunity on COMI (which is in watchlist)
    db.session.add(Opportunity(
        stock_id=s1.id, run_date=TODAY,
        opp_type="Breakout",
        entry_price=90.0, tp1_price=97.0, tp2_price=105.0, sl_price=86.0,
        radar_score=82.0, signal_quality="HIGH",
        outcome="PENDING", is_active=True,
    ))
    db.session.commit()

    # Score history (for as_of)
    db.session.add(RadarScoreHistory(
        stock_id=s1.id, run_date=TODAY, score=82.0,
        rvol=1.8, data_quality="HIGH",
    ))
    db.session.commit()


# ── Status & shape ────────────────────────────────────────────────────────────

def test_my_day_200(client):
    r = client.get("/api/my-day")
    assert r.status_code == 200


def test_my_day_shape(client):
    data = client.get("/api/my-day").get_json()
    for key in ("as_of", "is_authenticated", "portfolio",
                "watchlist_count", "watchlist_alerts",
                "unread_notifications", "active_opportunities"):
        assert key in data, f"missing key: {key}"


def test_my_day_empty_db(empty_client):
    r = empty_client.get("/api/my-day")
    assert r.status_code == 200


def test_my_day_empty_db_defaults(empty_client):
    data = empty_client.get("/api/my-day").get_json()
    assert data["portfolio"] is None
    assert data["watchlist_count"] == 0
    assert data["watchlist_alerts"] == []
    assert data["unread_notifications"] == 0
    assert data["active_opportunities"] == []


# ── is_authenticated ──────────────────────────────────────────────────────────

def test_is_authenticated_false_without_token(client):
    data = client.get("/api/my-day").get_json()
    assert data["is_authenticated"] is False


# ── as_of ─────────────────────────────────────────────────────────────────────

def test_as_of_present(client):
    data = client.get("/api/my-day").get_json()
    assert data["as_of"] == TODAY.isoformat()


# ── Portfolio ─────────────────────────────────────────────────────────────────

def test_portfolio_open_positions(client):
    data = client.get("/api/my-day").get_json()
    assert data["portfolio"]["open_positions"] == 2


def test_portfolio_total_invested(client):
    data = client.get("/api/my-day").get_json()
    # COMI: 100*90=9000, HRHO: 50*45=2250
    assert data["portfolio"]["total_invested"] == pytest.approx(11250.0)


def test_portfolio_unrealized_pnl(client):
    data = client.get("/api/my-day").get_json()
    # COMI: (95-90)*100=500, HRHO: (40-45)*50=-250 → net 250
    assert data["portfolio"]["unrealized_pnl"] == pytest.approx(250.0)


def test_portfolio_unrealized_pnl_pct(client):
    data = client.get("/api/my-day").get_json()
    # 250 / 11250 * 100 ≈ 2.22%
    assert data["portfolio"]["unrealized_pnl_pct"] == pytest.approx(2.22, abs=0.01)


def test_portfolio_none_when_no_holdings(empty_client):
    data = empty_client.get("/api/my-day").get_json()
    assert data["portfolio"] is None


# ── Watchlist ─────────────────────────────────────────────────────────────────

def test_watchlist_count(client):
    data = client.get("/api/my-day").get_json()
    assert data["watchlist_count"] == 3


def test_watchlist_alerts_count(client):
    data = client.get("/api/my-day").get_json()
    assert len(data["watchlist_alerts"]) == 2


def test_watchlist_alert_above_shape(client):
    data = client.get("/api/my-day").get_json()
    above_alerts = [a for a in data["watchlist_alerts"] if a["alert_type"] == "above"]
    assert len(above_alerts) == 1
    alert = above_alerts[0]
    assert alert["symbol"] == "COMI"
    assert alert["current_price"] == 95.0
    assert alert["alert_price"] == 90.0


def test_watchlist_alert_below_shape(client):
    data = client.get("/api/my-day").get_json()
    below_alerts = [a for a in data["watchlist_alerts"] if a["alert_type"] == "below"]
    assert len(below_alerts) == 1
    alert = below_alerts[0]
    assert alert["symbol"] == "HRHO"
    assert alert["current_price"] == 40.0
    assert alert["alert_price"] == 45.0


def test_watchlist_alert_item_shape(client):
    data = client.get("/api/my-day").get_json()
    alert = data["watchlist_alerts"][0]
    for key in ("symbol", "name_ar", "alert_type", "current_price", "alert_price"):
        assert key in alert


# ── Notifications ─────────────────────────────────────────────────────────────

def test_unread_notifications_count(client):
    data = client.get("/api/my-day").get_json()
    assert data["unread_notifications"] == 2


# ── Active opportunities ───────────────────────────────────────────────────────

def test_active_opportunities_for_watchlist(client):
    data = client.get("/api/my-day").get_json()
    assert len(data["active_opportunities"]) == 1
    opp = data["active_opportunities"][0]
    assert opp["symbol"] == "COMI"
    assert opp["opp_type"] == "Breakout"


def test_active_opportunity_shape(client):
    data = client.get("/api/my-day").get_json()
    opp = data["active_opportunities"][0]
    for key in ("symbol", "name_ar", "opp_type", "radar_score", "run_date"):
        assert key in opp


def test_no_opps_when_empty_watchlist(empty_client):
    data = empty_client.get("/api/my-day").get_json()
    assert data["active_opportunities"] == []
