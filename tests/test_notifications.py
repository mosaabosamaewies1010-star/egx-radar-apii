"""Tests for /api/notifications — list, mark read, mark all read, delete, clear."""
import pytest
from app import create_app, db
from app.models.notification import Notification, NOTIFICATION_TYPES


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
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def _make(title_ar="تنبيه اختباري", body_ar="نص التنبيه", ntype="regime_change", is_read=False):
    n = Notification(
        user_id=None,
        type=ntype,
        title_ar=title_ar,
        body_ar=body_ar,
        is_read=is_read,
    )
    db.session.add(n)
    db.session.commit()
    return n


def _notif_id(client) -> int:
    n = _make()
    return n.id


# ── List ──────────────────────────────────────────────────────────────────────

class TestNotificationList:
    def test_list_empty(self, client):
        data = client.get("/api/notifications").get_json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["unread"] == 0

    def test_list_returns_200(self, client):
        assert client.get("/api/notifications").status_code == 200

    def test_list_with_item(self, client):
        with client.application.app_context():
            _make("رأس المال صاعد")
        data = client.get("/api/notifications").get_json()
        assert len(data["items"]) == 1
        assert data["items"][0]["title_ar"] == "رأس المال صاعد"

    def test_unread_count(self, client):
        with client.application.app_context():
            _make(is_read=False)
            _make(is_read=True)
        data = client.get("/api/notifications").get_json()
        assert data["unread"] == 1

    def test_total_count_all(self, client):
        with client.application.app_context():
            _make()
            _make()
        data = client.get("/api/notifications").get_json()
        assert data["total"] == 2

    def test_unread_filter(self, client):
        with client.application.app_context():
            _make(is_read=False)
            _make(is_read=True)
        data = client.get("/api/notifications?unread=1").get_json()
        assert data["total"] == 1
        assert data["items"][0]["is_read"] is False

    def test_limit_param(self, client):
        with client.application.app_context():
            for i in range(5):
                _make(title_ar=f"تنبيه {i}")
        data = client.get("/api/notifications?limit=2").get_json()
        assert len(data["items"]) == 2
        assert data["limit"] == 2

    def test_offset_param(self, client):
        with client.application.app_context():
            for i in range(3):
                _make(title_ar=f"تنبيه {i}")
        data = client.get("/api/notifications?limit=2&offset=2").get_json()
        assert len(data["items"]) == 1

    def test_items_ordered_newest_first(self, client):
        with client.application.app_context():
            n1 = _make(title_ar="الأول")
            n2 = _make(title_ar="الثاني")
        data = client.get("/api/notifications").get_json()
        assert data["items"][0]["title_ar"] == "الثاني"

    def test_item_has_required_fields(self, client):
        with client.application.app_context():
            _make()
        item = client.get("/api/notifications").get_json()["items"][0]
        for field in ("id", "type", "title_ar", "body_ar", "is_read", "created_at"):
            assert field in item


# ── Mark single read ──────────────────────────────────────────────────────────

class TestMarkRead:
    def test_mark_read_returns_200(self, client):
        with client.application.app_context():
            nid = _make().id
        assert client.patch(f"/api/notifications/{nid}/read").status_code == 200

    def test_mark_read_sets_is_read_true(self, client):
        with client.application.app_context():
            nid = _make(is_read=False).id
        data = client.patch(f"/api/notifications/{nid}/read").get_json()
        assert data["is_read"] is True

    def test_mark_read_not_found(self, client):
        assert client.patch("/api/notifications/9999/read").status_code == 404

    def test_mark_read_persists_to_db(self, client):
        with client.application.app_context():
            nid = _make(is_read=False).id
        client.patch(f"/api/notifications/{nid}/read")
        with client.application.app_context():
            assert db.session.get(Notification, nid).is_read is True


# ── Mark all read ─────────────────────────────────────────────────────────────

class TestMarkAllRead:
    def test_mark_all_read_returns_200(self, client):
        assert client.patch("/api/notifications/read-all").status_code == 200

    def test_mark_all_read_sets_ok(self, client):
        assert client.patch("/api/notifications/read-all").get_json()["ok"] is True

    def test_mark_all_read_updates_all(self, client):
        with client.application.app_context():
            _make(is_read=False)
            _make(is_read=False)
        client.patch("/api/notifications/read-all")
        data = client.get("/api/notifications").get_json()
        assert data["unread"] == 0

    def test_mark_all_read_empty_ok(self, client):
        assert client.patch("/api/notifications/read-all").status_code == 200


# ── Delete single ─────────────────────────────────────────────────────────────

class TestDeleteNotification:
    def test_delete_returns_204(self, client):
        with client.application.app_context():
            nid = _make().id
        assert client.delete(f"/api/notifications/{nid}").status_code == 204

    def test_delete_removes_from_db(self, client):
        with client.application.app_context():
            nid = _make().id
        client.delete(f"/api/notifications/{nid}")
        with client.application.app_context():
            assert db.session.get(Notification, nid) is None

    def test_delete_not_found(self, client):
        assert client.delete("/api/notifications/9999").status_code == 404


# ── Clear read (bulk) ─────────────────────────────────────────────────────────

class TestClearRead:
    def test_clear_read_returns_200(self, client):
        assert client.delete("/api/notifications").status_code == 200

    def test_clear_read_removes_only_read(self, client):
        with client.application.app_context():
            _make(is_read=True)
            _make(is_read=True)
            _make(is_read=False)
        client.delete("/api/notifications")
        with client.application.app_context():
            assert Notification.query.count() == 1
            assert Notification.query.filter_by(is_read=False).count() == 1

    def test_clear_read_empty_ok(self, client):
        assert client.delete("/api/notifications").status_code == 200
