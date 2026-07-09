"""Tests for /api/portfolio — list, add, close, delete."""
import pytest
from app import create_app, db
from app.models.stock import Stock
from app.models.portfolio import PortfolioHolding


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
    s = Stock(symbol="COMI", name_ar="بنك القاهرة", name_en="CIB",
              sector="البنوك", is_sharia=False, last_price=90.0)
    db.session.add(s)
    db.session.commit()


def _add(client, symbol="COMI", quantity=100, avg_cost=87.5, notes=None):
    return client.post("/api/portfolio", json={
        "symbol": symbol, "quantity": quantity,
        "avg_cost": avg_cost, "notes": notes,
    })


# ── List ──────────────────────────────────────────────────────────────────────

class TestPortfolioList:
    def test_list_empty(self, client):
        data = client.get("/api/portfolio").get_json()
        assert data["holdings"] == []
        assert data["summary"]["open_positions"] == 0

    def test_list_returns_200(self, client):
        assert client.get("/api/portfolio").status_code == 200

    def test_list_with_holding(self, client):
        _add(client)
        data = client.get("/api/portfolio").get_json()
        assert len(data["holdings"]) == 1
        assert data["holdings"][0]["symbol"] == "COMI"

    def test_summary_total_invested(self, client):
        _add(client, quantity=100, avg_cost=87.5)   # cost_basis = 8750
        data = client.get("/api/portfolio").get_json()
        assert data["summary"]["total_invested"] == pytest.approx(8750.0)

    def test_summary_open_positions_count(self, client):
        _add(client)
        _add(client, quantity=50, avg_cost=80.0)
        data = client.get("/api/portfolio").get_json()
        assert data["summary"]["open_positions"] == 2

    def test_unrealized_pnl_computed_from_last_price(self, client):
        _add(client, quantity=100, avg_cost=87.5)   # last_price=90, unreal=(90-87.5)*100=250
        data = client.get("/api/portfolio").get_json()
        assert data["holdings"][0]["unrealized_pnl"] == pytest.approx(250.0)
        assert data["holdings"][0]["current_price"] == pytest.approx(90.0)

    def test_unrealized_pnl_pct_computed(self, client):
        _add(client, quantity=100, avg_cost=87.5)   # pct=(90-87.5)/87.5*100≈2.86%
        data = client.get("/api/portfolio").get_json()
        assert data["holdings"][0]["unrealized_pnl_pct"] == pytest.approx(2.86, abs=0.1)


# ── Add ───────────────────────────────────────────────────────────────────────

class TestPortfolioAdd:
    def test_add_success_status(self, client):
        assert _add(client).status_code == 201

    def test_add_returns_holding(self, client):
        data = _add(client).get_json()
        assert data["symbol"] == "COMI"
        assert data["quantity"] == 100
        assert data["avg_cost"] == pytest.approx(87.5)

    def test_add_is_open_true(self, client):
        assert _add(client).get_json()["is_open"] is True

    def test_add_missing_symbol(self, client):
        resp = client.post("/api/portfolio", json={"quantity": 100, "avg_cost": 87.5})
        assert resp.status_code == 422

    def test_add_zero_quantity(self, client):
        resp = client.post("/api/portfolio", json={"symbol": "COMI", "quantity": 0, "avg_cost": 87.5})
        assert resp.status_code == 422
        assert "كمية" in resp.get_json()["error"]

    def test_add_zero_cost(self, client):
        resp = client.post("/api/portfolio", json={"symbol": "COMI", "quantity": 100, "avg_cost": 0})
        assert resp.status_code == 422

    def test_add_unknown_stock(self, client):
        resp = _add(client, symbol="XXXX")
        assert resp.status_code == 404
        assert "غير موجود" in resp.get_json()["error"]

    def test_add_symbol_uppercased(self, client):
        resp = client.post("/api/portfolio", json={"symbol": "comi", "quantity": 10, "avg_cost": 90.0})
        assert resp.status_code == 201
        assert resp.get_json()["symbol"] == "COMI"

    def test_add_notes_stored(self, client):
        data = _add(client, notes="صفقة تجريبية").get_json()
        assert data["notes"] == "صفقة تجريبية"

    def test_add_persists_to_db(self, client):
        _add(client)
        assert PortfolioHolding.query.count() == 1


# ── Close ─────────────────────────────────────────────────────────────────────

class TestPortfolioClose:
    def _holding_id(self, client) -> int:
        return _add(client).get_json()["id"]

    def test_close_success_status(self, client):
        hid  = self._holding_id(client)
        resp = client.patch(f"/api/portfolio/{hid}/close", json={"close_price": 95.0})
        assert resp.status_code == 200

    def test_close_sets_closed_at(self, client):
        hid  = self._holding_id(client)
        data = client.patch(f"/api/portfolio/{hid}/close", json={"close_price": 95.0}).get_json()
        assert data["closed_at"] is not None

    def test_close_computes_realized_pnl(self, client):
        hid  = self._holding_id(client)   # qty=100, avg_cost=87.5, close=95
        data = client.patch(f"/api/portfolio/{hid}/close", json={"close_price": 95.0}).get_json()
        assert data["realized_pnl"] == pytest.approx(750.0)   # (95-87.5)*100

    def test_close_is_open_becomes_false(self, client):
        hid  = self._holding_id(client)
        data = client.patch(f"/api/portfolio/{hid}/close", json={"close_price": 95.0}).get_json()
        assert data["is_open"] is False

    def test_close_already_closed(self, client):
        hid = self._holding_id(client)
        client.patch(f"/api/portfolio/{hid}/close", json={"close_price": 95.0})
        resp = client.patch(f"/api/portfolio/{hid}/close", json={"close_price": 98.0})
        assert resp.status_code == 409

    def test_close_zero_price(self, client):
        hid  = self._holding_id(client)
        resp = client.patch(f"/api/portfolio/{hid}/close", json={"close_price": 0})
        assert resp.status_code == 422

    def test_close_not_found(self, client):
        resp = client.patch("/api/portfolio/9999/close", json={"close_price": 95.0})
        assert resp.status_code == 404

    def test_closed_holding_summary(self, client):
        hid = self._holding_id(client)
        client.patch(f"/api/portfolio/{hid}/close", json={"close_price": 95.0})
        data = client.get("/api/portfolio").get_json()
        assert data["summary"]["closed_positions"] == 1
        assert data["summary"]["total_realized_pnl"] == pytest.approx(750.0)


# ── Delete ────────────────────────────────────────────────────────────────────

class TestPortfolioDelete:
    def test_delete_success(self, client):
        hid  = _add(client).get_json()["id"]
        resp = client.delete(f"/api/portfolio/{hid}")
        assert resp.status_code == 204

    def test_delete_removes_from_db(self, client):
        hid = _add(client).get_json()["id"]
        client.delete(f"/api/portfolio/{hid}")
        assert PortfolioHolding.query.count() == 0

    def test_delete_not_found(self, client):
        resp = client.delete("/api/portfolio/9999")
        assert resp.status_code == 404
