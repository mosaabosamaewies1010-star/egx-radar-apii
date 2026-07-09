"""Tests for /api/watchlist — list, add, update, delete."""
import pytest
from app import create_app, db
from app.models.stock import Stock
from app.models.watchlist import Watchlist


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
               sector="البنوك", is_sharia=False, last_price=90.0, last_change_pct=1.5)
    s2 = Stock(symbol="HRHO", name_ar="هيرمس", name_en="Hermes",
               sector="الخدمات المالية", is_sharia=False, last_price=45.0, last_change_pct=-0.8)
    db.session.add_all([s1, s2])
    db.session.commit()


def _add(client, symbol="COMI", notes=None, above=None, below=None):
    return client.post("/api/watchlist", json={
        "symbol": symbol, "notes": notes,
        "alert_price_above": above, "alert_price_below": below,
    })


def _item_id(client, symbol="COMI") -> int:
    return _add(client, symbol).get_json()["id"]


# ── List ──────────────────────────────────────────────────────────────────────

class TestWatchlistList:
    def test_list_empty(self, client):
        data = client.get("/api/watchlist").get_json()
        assert data["items"] == []
        assert data["count"] == 0

    def test_list_returns_200(self, client):
        assert client.get("/api/watchlist").status_code == 200

    def test_list_with_item(self, client):
        _add(client)
        data = client.get("/api/watchlist").get_json()
        assert len(data["items"]) == 1
        assert data["items"][0]["symbol"] == "COMI"

    def test_list_count_matches_items(self, client):
        _add(client, "COMI")
        _add(client, "HRHO")
        data = client.get("/api/watchlist").get_json()
        assert data["count"] == 2

    def test_list_includes_last_price(self, client):
        _add(client)
        data = client.get("/api/watchlist").get_json()
        assert data["items"][0]["last_price"] == pytest.approx(90.0)

    def test_list_includes_last_change_pct(self, client):
        _add(client)
        data = client.get("/api/watchlist").get_json()
        assert data["items"][0]["last_change_pct"] == pytest.approx(1.5)

    def test_list_includes_sector(self, client):
        _add(client)
        data = client.get("/api/watchlist").get_json()
        assert data["items"][0]["sector"] == "البنوك"


# ── Add ───────────────────────────────────────────────────────────────────────

class TestWatchlistAdd:
    def test_add_success_status(self, client):
        assert _add(client).status_code == 201

    def test_add_returns_item(self, client):
        data = _add(client).get_json()
        assert data["symbol"] == "COMI"

    def test_add_missing_symbol(self, client):
        resp = client.post("/api/watchlist", json={})
        assert resp.status_code == 422

    def test_add_unknown_symbol(self, client):
        resp = _add(client, symbol="XXXX")
        assert resp.status_code == 404
        assert "غير موجود" in resp.get_json()["error"]

    def test_add_symbol_uppercased(self, client):
        resp = client.post("/api/watchlist", json={"symbol": "comi"})
        assert resp.status_code == 201
        assert resp.get_json()["symbol"] == "COMI"

    def test_add_duplicate_returns_409(self, client):
        _add(client)
        resp = _add(client)
        assert resp.status_code == 409
        assert "موجود بالفعل" in resp.get_json()["error"]

    def test_add_notes_stored(self, client):
        data = _add(client, notes="سهم مميز").get_json()
        assert data["notes"] == "سهم مميز"

    def test_add_alert_above_stored(self, client):
        data = _add(client, above=100.0).get_json()
        assert data["alert_price_above"] == pytest.approx(100.0)

    def test_add_alert_below_stored(self, client):
        data = _add(client, below=80.0).get_json()
        assert data["alert_price_below"] == pytest.approx(80.0)

    def test_add_invalid_alert_above(self, client):
        resp = _add(client, above=-5)
        assert resp.status_code == 422

    def test_add_persists_to_db(self, client):
        _add(client)
        assert Watchlist.query.count() == 1


# ── Update ────────────────────────────────────────────────────────────────────

class TestWatchlistUpdate:
    def test_update_notes(self, client):
        wid = _item_id(client)
        data = client.patch(f"/api/watchlist/{wid}", json={"notes": "ملاحظة جديدة"}).get_json()
        assert data["notes"] == "ملاحظة جديدة"

    def test_update_alert_above(self, client):
        wid = _item_id(client)
        data = client.patch(f"/api/watchlist/{wid}", json={"alert_price_above": 95.0}).get_json()
        assert data["alert_price_above"] == pytest.approx(95.0)

    def test_update_alert_below(self, client):
        wid = _item_id(client)
        data = client.patch(f"/api/watchlist/{wid}", json={"alert_price_below": 85.0}).get_json()
        assert data["alert_price_below"] == pytest.approx(85.0)

    def test_update_clears_alert_with_null(self, client):
        wid = _item_id(client)
        client.patch(f"/api/watchlist/{wid}", json={"alert_price_above": 100.0})
        data = client.patch(f"/api/watchlist/{wid}", json={"alert_price_above": None}).get_json()
        assert data["alert_price_above"] is None

    def test_update_returns_200(self, client):
        wid = _item_id(client)
        assert client.patch(f"/api/watchlist/{wid}", json={"notes": "x"}).status_code == 200

    def test_update_not_found(self, client):
        assert client.patch("/api/watchlist/9999", json={"notes": "x"}).status_code == 404

    def test_update_invalid_alert(self, client):
        wid = _item_id(client)
        resp = client.patch(f"/api/watchlist/{wid}", json={"alert_price_above": 0})
        assert resp.status_code == 422


# ── Delete ────────────────────────────────────────────────────────────────────

class TestWatchlistDelete:
    def test_delete_success(self, client):
        wid = _item_id(client)
        assert client.delete(f"/api/watchlist/{wid}").status_code == 204

    def test_delete_removes_from_db(self, client):
        wid = _item_id(client)
        client.delete(f"/api/watchlist/{wid}")
        assert Watchlist.query.count() == 0

    def test_delete_not_found(self, client):
        assert client.delete("/api/watchlist/9999").status_code == 404

    def test_delete_then_readd_succeeds(self, client):
        wid = _item_id(client)
        client.delete(f"/api/watchlist/{wid}")
        assert _add(client).status_code == 201
