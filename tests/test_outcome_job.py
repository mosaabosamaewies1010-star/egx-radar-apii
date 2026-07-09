"""Tests for outcome_job — auto-close PENDING opportunities."""
import pytest
from datetime import date, datetime, timezone
from unittest.mock import patch, MagicMock

from app import create_app, db
from app.models import Stock, Opportunity, StrategyVersion
from app.jobs.outcome_job import _classify_exit, run_outcome_job


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    application = create_app("testing")
    application.config["TESTING"] = True
    application.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def stock(app):
    with app.app_context():
        s = Stock(symbol="COMI", name_ar="التجاري", sector="بنوك", is_sharia=False)
        db.session.add(s)
        db.session.commit()
        return s.id


def _make_opp(app, stock_id, entry=10.0, tp1=11.0, tp2=12.0, sl=9.5,
              max_hold=20, run_date=None, outcome="PENDING"):
    with app.app_context():
        o = Opportunity(
            stock_id=stock_id,
            run_date=run_date or date(2024, 1, 1),
            opp_type="Breakout",
            entry_price=entry,
            tp1_price=tp1,
            tp2_price=tp2,
            sl_price=sl,
            max_hold_days=max_hold,
            radar_score=70.0,
            outcome=outcome,
        )
        db.session.add(o)
        db.session.commit()
        return o.id


# ── Unit tests for _classify_exit ─────────────────────────────────────────────

class TestClassifyExit:
    def _opp(self):
        """Fake Opportunity object — run_date=today so no timeout fires."""
        o = MagicMock()
        o.entry_price   = 10.0
        o.tp1_price     = 11.0
        o.tp2_price     = 12.0
        o.sl_price      = 9.5
        o.max_hold_days = 20
        o.run_date      = date.today()
        return o

    def test_tp2_hit(self):
        assert _classify_exit(self._opp(), 12.0) == ("WIN", "TP2", 12.0)

    def test_tp2_exceeded(self):
        result = _classify_exit(self._opp(), 13.5)
        assert result[0] == "WIN" and result[1] == "TP2"

    def test_tp1_hit(self):
        assert _classify_exit(self._opp(), 11.0) == ("WIN", "TP1", 11.0)

    def test_tp1_between_tp1_tp2(self):
        result = _classify_exit(self._opp(), 11.5)
        assert result[0] == "WIN" and result[1] == "TP1"

    def test_sl_hit(self):
        result = _classify_exit(self._opp(), 9.5)
        assert result[0] == "LOSS" and result[1] == "SL"

    def test_sl_breached(self):
        result = _classify_exit(self._opp(), 8.0)
        assert result[0] == "LOSS" and result[1] == "SL"

    def test_price_between_sl_tp1_open(self):
        assert _classify_exit(self._opp(), 10.5) is None

    def test_timeout_expired(self):
        o = self._opp()
        o.run_date = date(2023, 12, 1)   # 31+ days ago
        result = _classify_exit(o, 10.3)
        assert result[0] == "EXPIRED" and result[1] == "timeout"

    def test_tp2_priority_over_tp1(self):
        """When price >= tp2, should return TP2 not TP1."""
        result = _classify_exit(self._opp(), 12.5)
        assert result[1] == "TP2"


# ── Integration tests for run_outcome_job ─────────────────────────────────────

class TestRunOutcomeJob:
    def test_closes_tp1_hit(self, app, stock):
        opp_id = _make_opp(app, stock, entry=10.0, tp1=11.0, tp2=12.0, sl=9.5)
        with patch("app.jobs.outcome_job._fetch_last_close", return_value=11.0):
            run_outcome_job(app)
        with app.app_context():
            opp = Opportunity.query.get(opp_id)
            assert opp.outcome     == "WIN"
            assert opp.exit_reason == "TP1"

    def test_closes_sl_hit(self, app, stock):
        opp_id = _make_opp(app, stock, entry=10.0, tp1=11.0, tp2=12.0, sl=9.5)
        with patch("app.jobs.outcome_job._fetch_last_close", return_value=9.3):
            run_outcome_job(app)
        with app.app_context():
            opp = Opportunity.query.get(opp_id)
            assert opp.outcome     == "LOSS"
            assert opp.exit_reason == "SL"

    def test_closes_expired(self, app, stock):
        opp_id = _make_opp(app, stock, max_hold=5, run_date=date(2023, 1, 1))
        with patch("app.jobs.outcome_job._fetch_last_close", return_value=10.1):
            run_outcome_job(app)
        with app.app_context():
            opp = Opportunity.query.get(opp_id)
            assert opp.outcome == "EXPIRED"

    def test_pnl_computed_win(self, app, stock):
        opp_id = _make_opp(app, stock, entry=10.0, tp1=11.0, tp2=12.0, sl=9.5)
        with patch("app.jobs.outcome_job._fetch_last_close", return_value=11.0):
            run_outcome_job(app)
        with app.app_context():
            opp = Opportunity.query.get(opp_id)
            assert opp.pnl_pct == pytest.approx(10.0)

    def test_pnl_computed_loss(self, app, stock):
        opp_id = _make_opp(app, stock, entry=10.0, tp1=11.0, tp2=12.0, sl=9.5)
        with patch("app.jobs.outcome_job._fetch_last_close", return_value=9.5):
            run_outcome_job(app)
        with app.app_context():
            opp = Opportunity.query.get(opp_id)
            assert opp.pnl_pct == pytest.approx(-5.0)

    def test_hold_days_set(self, app, stock):
        run_date = date(2024, 1, 1)
        opp_id   = _make_opp(app, stock, run_date=run_date)
        with patch("app.jobs.outcome_job._fetch_last_close", return_value=11.0):
            run_outcome_job(app)
        with app.app_context():
            opp = Opportunity.query.get(opp_id)
            assert opp.hold_days is not None
            assert opp.hold_days >= 0

    def test_skips_non_pending(self, app, stock):
        opp_id = _make_opp(app, stock, outcome="WIN")
        with patch("app.jobs.outcome_job._fetch_last_close", return_value=9.0):
            run_outcome_job(app)
        with app.app_context():
            opp = Opportunity.query.get(opp_id)
            assert opp.outcome == "WIN"   # not changed

    def test_skips_when_price_unavailable(self, app, stock):
        opp_id = _make_opp(app, stock)
        with patch("app.jobs.outcome_job._fetch_last_close", return_value=None):
            run_outcome_job(app)
        with app.app_context():
            opp = Opportunity.query.get(opp_id)
            assert opp.outcome == "PENDING"   # unchanged

    def test_leaves_open_position_pending(self, app, stock):
        opp_id = _make_opp(app, stock, entry=10.0, tp1=11.0, sl=9.5,
                            run_date=date.today())
        with patch("app.jobs.outcome_job._fetch_last_close", return_value=10.3):
            run_outcome_job(app)
        with app.app_context():
            opp = Opportunity.query.get(opp_id)
            assert opp.outcome == "PENDING"

    def test_no_pending_no_crash(self, app):
        """Job should exit cleanly with no PENDING rows."""
        run_outcome_job(app)   # should not raise
