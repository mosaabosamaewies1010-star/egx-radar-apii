"""Tests for /api/payments/* — plans, subscribe, history, confirm."""
import pytest
from flask_jwt_extended import create_access_token
from app import create_app, db
from app.models.user import User
from app.models.payment import Payment


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
        _seed(app)
        yield app.test_client(), app
        db.session.remove()
        db.drop_all()


def _seed(app):
    with app.app_context():
        u1 = User(email="user@test.com", name="Test")
        u1.set_password("password123")
        u2 = User(email="pro@test.com", name="ProUser", is_pro=True)
        u2.set_password("password123")
        db.session.add_all([u1, u2])
        db.session.commit()


def _auth_header(app, user_id: int) -> dict:
    with app.app_context():
        token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def get_user_id(app, email: str) -> int:
    with app.app_context():
        return User.query.filter_by(email=email).first().id


# ── GET /api/payments/plans ───────────────────────────────────────────────────

def test_plans_200(client):
    c, _ = client
    r = c.get("/api/payments/plans")
    assert r.status_code == 200


def test_plans_shape(client):
    c, _ = client
    data = c.get("/api/payments/plans").get_json()
    assert "plans" in data
    assert "features" in data


def test_plans_contains_pro_monthly(client):
    c, _ = client
    data = c.get("/api/payments/plans").get_json()
    ids = [p["id"] for p in data["plans"]]
    assert "pro_monthly" in ids


def test_plans_contains_pro_annual(client):
    c, _ = client
    data = c.get("/api/payments/plans").get_json()
    ids = [p["id"] for p in data["plans"]]
    assert "pro_annual" in ids


def test_plans_monthly_price(client):
    c, _ = client
    data = c.get("/api/payments/plans").get_json()
    monthly = next(p for p in data["plans"] if p["id"] == "pro_monthly")
    assert monthly["price"] == 199.0
    assert monthly["currency"] == "EGP"


def test_plans_annual_has_savings(client):
    c, _ = client
    data = c.get("/api/payments/plans").get_json()
    annual = next(p for p in data["plans"] if p["id"] == "pro_annual")
    assert annual["savings"] is not None


def test_plans_features_list(client):
    c, _ = client
    data = c.get("/api/payments/plans").get_json()
    assert isinstance(data["features"], list)
    assert len(data["features"]) > 0


# ── POST /api/payments/subscribe ─────────────────────────────────────────────

def test_subscribe_requires_auth(client):
    c, _ = client
    r = c.post("/api/payments/subscribe", json={"plan": "pro_monthly"})
    assert r.status_code == 401


def test_subscribe_201(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    r = c.post("/api/payments/subscribe",
               json={"plan": "pro_monthly"},
               headers=_auth_header(app, uid))
    assert r.status_code == 201


def test_subscribe_returns_payment(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    data = c.post("/api/payments/subscribe",
                  json={"plan": "pro_monthly"},
                  headers=_auth_header(app, uid)).get_json()
    assert "payment" in data
    assert data["payment"]["plan"] == "pro_monthly"
    assert data["payment"]["status"] == "pending"


def test_subscribe_returns_provider_ref(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    data = c.post("/api/payments/subscribe",
                  json={"plan": "pro_monthly"},
                  headers=_auth_header(app, uid)).get_json()
    assert "provider_ref" in data
    assert data["provider_ref"].startswith("EGX-")


def test_subscribe_invalid_plan_422(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    r = c.post("/api/payments/subscribe",
               json={"plan": "invalid_plan"},
               headers=_auth_header(app, uid))
    assert r.status_code == 422


def test_subscribe_already_pro_409(client):
    c, app = client
    uid = get_user_id(app, "pro@test.com")
    r = c.post("/api/payments/subscribe",
               json={"plan": "pro_monthly"},
               headers=_auth_header(app, uid))
    assert r.status_code == 409


def test_subscribe_annual_plan(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    data = c.post("/api/payments/subscribe",
                  json={"plan": "pro_annual"},
                  headers=_auth_header(app, uid)).get_json()
    assert data["payment"]["amount"] == 1799.0


# ── GET /api/payments/history ─────────────────────────────────────────────────

def test_history_requires_auth(client):
    c, _ = client
    r = c.get("/api/payments/history")
    assert r.status_code == 401


def test_history_empty(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    data = c.get("/api/payments/history",
                 headers=_auth_header(app, uid)).get_json()
    assert data["total"] == 0
    assert data["items"] == []


def test_history_after_subscribe(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    headers = _auth_header(app, uid)
    c.post("/api/payments/subscribe", json={"plan": "pro_monthly"}, headers=headers)
    data = c.get("/api/payments/history", headers=headers).get_json()
    assert data["total"] == 1
    assert data["items"][0]["plan"] == "pro_monthly"


def test_history_item_shape(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    headers = _auth_header(app, uid)
    c.post("/api/payments/subscribe", json={"plan": "pro_monthly"}, headers=headers)
    item = c.get("/api/payments/history", headers=headers).get_json()["items"][0]
    for key in ("id", "user_id", "plan", "amount", "currency", "status", "provider_ref", "created_at"):
        assert key in item


# ── PATCH /api/payments/<id>/confirm ──────────────────────────────────────────

def test_confirm_requires_auth(client):
    c, _ = client
    r = c.patch("/api/payments/1/confirm")
    assert r.status_code == 401


def test_confirm_200(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    headers = _auth_header(app, uid)
    pay_id = c.post("/api/payments/subscribe",
                    json={"plan": "pro_monthly"},
                    headers=headers).get_json()["payment"]["id"]
    r = c.patch(f"/api/payments/{pay_id}/confirm", headers=headers)
    assert r.status_code == 200


def test_confirm_sets_completed(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    headers = _auth_header(app, uid)
    pay_id = c.post("/api/payments/subscribe",
                    json={"plan": "pro_monthly"},
                    headers=headers).get_json()["payment"]["id"]
    data = c.patch(f"/api/payments/{pay_id}/confirm", headers=headers).get_json()
    assert data["payment"]["status"] == "completed"
    assert data["is_pro"] is True


def test_confirm_activates_pro(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    headers = _auth_header(app, uid)
    pay_id = c.post("/api/payments/subscribe",
                    json={"plan": "pro_monthly"},
                    headers=headers).get_json()["payment"]["id"]
    c.patch(f"/api/payments/{pay_id}/confirm", headers=headers)
    with app.app_context():
        user = db.session.get(User, uid)
        assert user.is_pro is True


def test_confirm_already_completed_422(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    headers = _auth_header(app, uid)
    pay_id = c.post("/api/payments/subscribe",
                    json={"plan": "pro_monthly"},
                    headers=headers).get_json()["payment"]["id"]
    c.patch(f"/api/payments/{pay_id}/confirm", headers=headers)
    r = c.patch(f"/api/payments/{pay_id}/confirm", headers=headers)
    assert r.status_code == 422


def test_confirm_not_found_404(client):
    c, app = client
    uid = get_user_id(app, "user@test.com")
    r = c.patch("/api/payments/9999/confirm", headers=_auth_header(app, uid))
    assert r.status_code == 404


def test_confirm_wrong_user_403(client):
    c, app = client
    uid1 = get_user_id(app, "user@test.com")
    uid2 = get_user_id(app, "pro@test.com")
    # uid2 is pro, so subscribe won't work — create payment directly
    with app.app_context():
        pay = Payment(user_id=uid1, plan="pro_monthly", amount=199.0, status="pending")
        db.session.add(pay)
        db.session.commit()
        pay_id = pay.id
    r = c.patch(f"/api/payments/{pay_id}/confirm",
                headers=_auth_header(app, uid2))
    assert r.status_code == 403
