"""Tests for /api/auth/* — register, login, me."""
import pytest
from app import create_app, db
from app.models.user import User


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["CACHE_TYPE"] = "SimpleCache"
    app.config["JWT_SECRET_KEY"] = "test-secret"
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def _register(client, email="user@example.com", password="password123", name="Test User"):
    return client.post("/api/auth/register", json={"email": email, "password": password, "name": name})


def _login(client, email="user@example.com", password="password123"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ── Register ──────────────────────────────────────────────────────────────────

class TestRegister:
    def test_register_success_status(self, client):
        resp = _register(client)
        assert resp.status_code == 201

    def test_register_returns_token(self, client):
        data = _register(client).get_json()
        assert "token" in data
        assert len(data["token"]) > 20

    def test_register_returns_user(self, client):
        data = _register(client).get_json()
        assert data["user"]["email"] == "user@example.com"
        assert data["user"]["name"]  == "Test User"

    def test_register_password_not_in_response(self, client):
        data = _register(client).get_json()
        assert "password" not in data["user"]
        assert "password_hash" not in data["user"]

    def test_register_duplicate_email(self, client):
        _register(client)
        resp = _register(client)
        assert resp.status_code == 409
        assert "مستخدم" in resp.get_json()["error"]

    def test_register_invalid_email(self, client):
        resp = _register(client, email="notanemail")
        assert resp.status_code == 422

    def test_register_short_password(self, client):
        resp = _register(client, password="abc")
        assert resp.status_code == 422
        assert "8 أحرف" in resp.get_json()["error"]

    def test_register_optional_name(self, client):
        resp = client.post("/api/auth/register", json={"email": "x@x.com", "password": "longpassword"})
        assert resp.status_code == 201
        assert resp.get_json()["user"]["name"] is None

    def test_register_creates_db_record(self, client):
        _register(client)
        with client.application.app_context():
            assert User.query.count() == 1

    def test_register_email_lowercased(self, client):
        _register(client, email="USER@EXAMPLE.COM")
        with client.application.app_context():
            assert User.query.filter_by(email="user@example.com").first() is not None


# ── Login ─────────────────────────────────────────────────────────────────────

class TestLogin:
    def test_login_success_status(self, client):
        _register(client)
        assert _login(client).status_code == 200

    def test_login_returns_token(self, client):
        _register(client)
        data = _login(client).get_json()
        assert "token" in data
        assert len(data["token"]) > 20

    def test_login_returns_user_profile(self, client):
        _register(client)
        data = _login(client).get_json()
        assert data["user"]["email"] == "user@example.com"

    def test_login_wrong_password(self, client):
        _register(client)
        resp = _login(client, password="wrongpassword")
        assert resp.status_code == 401

    def test_login_nonexistent_email(self, client):
        resp = _login(client, email="nobody@example.com")
        assert resp.status_code == 401

    def test_login_error_message_arabic(self, client):
        resp = _login(client, email="nobody@example.com")
        assert "غير صحيحة" in resp.get_json()["error"]

    def test_login_inactive_user(self, client):
        _register(client)
        with client.application.app_context():
            u = User.query.first()
            u.is_active = False
            db.session.commit()
        resp = _login(client)
        assert resp.status_code == 403

    def test_login_case_insensitive_email(self, client):
        _register(client, email="user@example.com")
        resp = _login(client, email="USER@EXAMPLE.COM")
        assert resp.status_code == 200


# ── Me ────────────────────────────────────────────────────────────────────────

class TestMe:
    def _token(self, client) -> str:
        _register(client)
        return _login(client).get_json()["token"]

    def test_me_success(self, client):
        token = self._token(client)
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_me_returns_user_data(self, client):
        token = self._token(client)
        data = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).get_json()
        assert data["email"] == "user@example.com"

    def test_me_no_token(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_invalid_token(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer invalidtoken"})
        assert resp.status_code == 422

    def test_me_password_not_exposed(self, client):
        token = self._token(client)
        data = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).get_json()
        assert "password" not in data
        assert "password_hash" not in data
