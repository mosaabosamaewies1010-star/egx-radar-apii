"""Tests for Platform Foundation models: Watchlist, PortfolioHolding, Notification."""
from datetime import datetime, timezone
import pytest

from app import create_app, db
from app.models.stock import Stock
from app.models.watchlist import Watchlist
from app.models.portfolio import PortfolioHolding
from app.models.notification import Notification, NOTIFICATION_TYPES


@pytest.fixture()
def ctx():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _make_stock(ctx) -> Stock:
    s = Stock(symbol="COMI", name_ar="بنك القاهرة", name_en="CIB",
              sector="البنوك", is_sharia=False)
    db.session.add(s)
    db.session.flush()
    return s


# ── Watchlist ─────────────────────────────────────────────────────────────────

class TestWatchlist:
    def test_create_watchlist_entry(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            w = Watchlist(stock_id=stock.id, user_id=None, notes="tracking")
            db.session.add(w)
            db.session.commit()
            assert Watchlist.query.count() == 1

    def test_watchlist_to_dict_has_symbol(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            w = Watchlist(stock_id=stock.id)
            db.session.add(w)
            db.session.commit()
            d = w.to_dict()
            assert d["symbol"] == "COMI"
            assert d["name_ar"] == "بنك القاهرة"

    def test_watchlist_alert_prices(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            w = Watchlist(stock_id=stock.id, alert_price_above=95.0, alert_price_below=80.0)
            db.session.add(w)
            db.session.commit()
            d = w.to_dict()
            assert d["alert_price_above"] == 95.0
            assert d["alert_price_below"] == 80.0

    def test_watchlist_created_at_is_set(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            w = Watchlist(stock_id=stock.id)
            db.session.add(w)
            db.session.commit()
            assert w.created_at is not None
            assert isinstance(w.created_at, datetime)

    def test_watchlist_cascades_stock_relationship(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            w = Watchlist(stock_id=stock.id)
            db.session.add(w)
            db.session.commit()
            fetched = Watchlist.query.first()
            assert fetched.stock.symbol == "COMI"


# ── PortfolioHolding ──────────────────────────────────────────────────────────

class TestPortfolioHolding:
    def test_create_open_position(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            h = PortfolioHolding(stock_id=stock.id, quantity=100, avg_cost=87.5)
            db.session.add(h)
            db.session.commit()
            assert PortfolioHolding.query.count() == 1

    def test_is_open_when_not_closed(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            h = PortfolioHolding(stock_id=stock.id, quantity=100, avg_cost=87.5)
            db.session.add(h)
            db.session.commit()
            assert h.is_open is True

    def test_realized_pnl_none_when_open(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            h = PortfolioHolding(stock_id=stock.id, quantity=100, avg_cost=87.5)
            db.session.add(h)
            db.session.commit()
            assert h.realized_pnl is None

    def test_realized_pnl_computed_when_closed(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            now = datetime.now(timezone.utc)
            h = PortfolioHolding(
                stock_id=stock.id, quantity=100, avg_cost=80.0,
                closed_at=now, close_price=93.0,
            )
            db.session.add(h)
            db.session.commit()
            assert h.realized_pnl == pytest.approx(1300.0, abs=0.01)  # (93-80)*100

    def test_cost_basis_computed(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            h = PortfolioHolding(stock_id=stock.id, quantity=200, avg_cost=50.0)
            db.session.add(h)
            db.session.commit()
            assert h.cost_basis == pytest.approx(10_000.0)

    def test_to_dict_has_required_keys(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            h = PortfolioHolding(stock_id=stock.id, quantity=50, avg_cost=90.0)
            db.session.add(h)
            db.session.commit()
            d = h.to_dict()
            for key in ("symbol", "quantity", "avg_cost", "cost_basis", "is_open", "realized_pnl"):
                assert key in d, f"Missing key: {key}"

    def test_currency_defaults_to_egp(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            h = PortfolioHolding(stock_id=stock.id, quantity=10, avg_cost=100.0)
            db.session.add(h)
            db.session.commit()
            assert h.currency == "EGP"

    def test_is_open_false_when_closed(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            h = PortfolioHolding(
                stock_id=stock.id, quantity=100, avg_cost=80.0,
                closed_at=datetime.now(timezone.utc), close_price=85.0,
            )
            db.session.add(h)
            db.session.commit()
            assert h.is_open is False


# ── Notification ──────────────────────────────────────────────────────────────

class TestNotification:
    def test_create_notification(self, ctx):
        with ctx.app_context():
            n = Notification(type="regime_change", title_ar="تغير النظام السوقي")
            db.session.add(n)
            db.session.commit()
            assert Notification.query.count() == 1

    def test_notification_unread_by_default(self, ctx):
        with ctx.app_context():
            n = Notification(type="morning_brief", title_ar="موجز الصباح")
            db.session.add(n)
            db.session.commit()
            assert n.is_read is False

    def test_notification_mark_read(self, ctx):
        with ctx.app_context():
            n = Notification(type="morning_brief", title_ar="موجز الصباح")
            db.session.add(n)
            db.session.commit()
            n.is_read = True
            db.session.commit()
            assert Notification.query.first().is_read is True

    def test_notification_with_stock(self, ctx):
        with ctx.app_context():
            stock = _make_stock(ctx)
            n = Notification(
                stock_id=stock.id,
                type="new_opportunity",
                title_ar="فرصة جديدة: COMI",
            )
            db.session.add(n)
            db.session.commit()
            d = n.to_dict()
            assert d["symbol"] == "COMI"
            assert d["type"] == "new_opportunity"

    def test_notification_types_constant(self, ctx):
        expected = {
            "score_change", "new_opportunity", "sl_alert",
            "tp_reached", "regime_change", "morning_brief",
        }
        assert set(NOTIFICATION_TYPES) == expected

    def test_notification_to_dict_keys(self, ctx):
        with ctx.app_context():
            n = Notification(type="regime_change", title_ar="تغير", body_ar="تفاصيل")
            db.session.add(n)
            db.session.commit()
            d = n.to_dict()
            for key in ("id", "type", "title_ar", "body_ar", "is_read", "created_at"):
                assert key in d, f"Missing key: {key}"

    def test_notification_created_at_auto(self, ctx):
        with ctx.app_context():
            n = Notification(type="sl_alert", title_ar="تنبيه وقف الخسارة")
            db.session.add(n)
            db.session.commit()
            assert n.created_at is not None


# ── Scheduler (unit test — no actual scheduling) ──────────────────────────────

class TestScheduler:
    def test_create_scheduler_returns_scheduler(self, ctx):
        from app.jobs.scheduler import create_scheduler
        sched = create_scheduler(ctx)
        jobs = sched.get_jobs()
        job_ids = {j.id for j in jobs}
        assert "regime_job" in job_ids
        assert "daily_scan" in job_ids

    def test_scheduler_has_three_jobs(self, ctx):
        from app.jobs.scheduler import create_scheduler
        sched = create_scheduler(ctx)
        assert len(sched.get_jobs()) == 3

    def test_scheduler_has_outcome_job(self, ctx):
        from app.jobs.scheduler import create_scheduler
        sched = create_scheduler(ctx)
        job_ids = {j.id for j in sched.get_jobs()}
        assert "outcome_job" in job_ids
