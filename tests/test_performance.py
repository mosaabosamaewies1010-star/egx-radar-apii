"""Tests for GET /api/performance — Decision Moat endpoint."""
import pytest
from datetime import date, datetime, timezone

from app import create_app, db
from app.models import Stock, Opportunity, StrategyVersion


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
def client(app):
    return app.test_client()


@pytest.fixture
def seed(app):
    """Seed minimal data: 1 version, 2 stocks, 6 trades."""
    with app.app_context():
        ver = StrategyVersion(
            version="test_v1",
            description="Test version",
            effective_from=date(2022, 1, 1),
        )
        db.session.add(ver)
        db.session.flush()

        s1 = Stock(symbol="COMI", name_ar="التجاري الدولي", sector="بنوك", is_sharia=False)
        s2 = Stock(symbol="FAISAL", name_ar="فيصل", sector="بنوك", is_sharia=True)
        db.session.add_all([s1, s2])
        db.session.flush()

        def _opp(stock, outcome, pnl, year, exit_reason, snapshot_sector="بنوك"):
            o = Opportunity(
                stock_id=stock.id,
                opp_type="Breakout",
                radar_score=75,
                signal_quality="HIGH",
                entry_price=10.0,
                tp1_price=11.0,
                tp2_price=12.0,
                sl_price=9.5,
                run_date=datetime(year, 6, 1, tzinfo=timezone.utc),
                outcome=outcome,
                pnl_pct=pnl,
                hold_days=10,
                exit_reason=exit_reason,
                strategy_version_id=ver.id,
                feature_snapshot={"sector": snapshot_sector, "rsi": 55.0},
            )
            return o

        trades = [
            # 3 x COMI: 2 WIN, 1 LOSS
            _opp(s1, "WIN",  10.0, 2023, "TP1"),
            _opp(s1, "WIN",   8.0, 2024, "TP2"),
            _opp(s1, "LOSS", -5.0, 2024, "SL"),
            # 3 x FAISAL: 1 WIN, 2 LOSS
            _opp(s2, "WIN",   6.0, 2023, "TP1"),
            _opp(s2, "LOSS", -4.0, 2023, "SL"),
            _opp(s2, "LOSS", -3.0, 2024, "SL"),
        ]
        db.session.add_all(trades)
        db.session.commit()

        yield {"ver_id": ver.id, "s1_id": s1.id, "s2_id": s2.id}


# ── Empty DB ──────────────────────────────────────────────────────────────────


class TestPerformanceEmpty:
    def test_empty_db_returns_200(self, client):
        res = client.get("/api/performance")
        assert res.status_code == 200

    def test_empty_db_has_total_zero(self, client):
        data = client.get("/api/performance").get_json()
        assert data["total"] == 0


# ── Response shape ────────────────────────────────────────────────────────────


class TestPerformanceShape:
    def test_overall_present(self, client, seed):
        data = client.get("/api/performance").get_json()
        assert "overall" in data

    def test_by_year_present(self, client, seed):
        data = client.get("/api/performance").get_json()
        assert "by_year" in data

    def test_by_sector_present(self, client, seed):
        data = client.get("/api/performance").get_json()
        assert "by_sector" in data

    def test_by_version_present(self, client, seed):
        data = client.get("/api/performance").get_json()
        assert "by_version" in data

    def test_top_stocks_present(self, client, seed):
        data = client.get("/api/performance").get_json()
        assert "top_stocks" in data

    def test_overall_has_required_keys(self, client, seed):
        overall = client.get("/api/performance").get_json()["overall"]
        required = {"total", "closed", "wins", "losses", "win_rate",
                    "avg_win_pct", "avg_loss_pct", "profit_factor",
                    "expectancy", "avg_hold_days", "tp1_rate", "sl_rate"}
        assert required.issubset(overall.keys())


# ── Overall stats ─────────────────────────────────────────────────────────────


class TestPerformanceOverall:
    def test_total_count(self, client, seed):
        overall = client.get("/api/performance").get_json()["overall"]
        assert overall["total"] == 6

    def test_wins_count(self, client, seed):
        overall = client.get("/api/performance").get_json()["overall"]
        assert overall["wins"] == 3

    def test_losses_count(self, client, seed):
        overall = client.get("/api/performance").get_json()["overall"]
        assert overall["losses"] == 3

    def test_win_rate_50pct(self, client, seed):
        overall = client.get("/api/performance").get_json()["overall"]
        assert overall["win_rate"] == pytest.approx(50.0, abs=0.1)

    def test_profit_factor_positive(self, client, seed):
        overall = client.get("/api/performance").get_json()["overall"]
        assert overall["profit_factor"] is not None
        assert overall["profit_factor"] > 1

    def test_avg_win_positive(self, client, seed):
        overall = client.get("/api/performance").get_json()["overall"]
        assert overall["avg_win_pct"] > 0

    def test_avg_loss_negative(self, client, seed):
        overall = client.get("/api/performance").get_json()["overall"]
        assert overall["avg_loss_pct"] < 0

    def test_tp1_rate(self, client, seed):
        # 2 TP1 exits out of 6 closed = 33.3%
        overall = client.get("/api/performance").get_json()["overall"]
        assert overall["tp1_rate"] == pytest.approx(33.3, abs=0.2)

    def test_sl_rate(self, client, seed):
        # 3 SL exits out of 6 closed = 50%
        overall = client.get("/api/performance").get_json()["overall"]
        assert overall["sl_rate"] == pytest.approx(50.0, abs=0.1)

    def test_avg_hold_days(self, client, seed):
        overall = client.get("/api/performance").get_json()["overall"]
        assert overall["avg_hold_days"] == pytest.approx(10.0, abs=0.1)


# ── By year ───────────────────────────────────────────────────────────────────


class TestPerformanceByYear:
    def test_two_years_present(self, client, seed):
        by_year = client.get("/api/performance").get_json()["by_year"]
        years = [r["year"] for r in by_year]
        assert 2023 in years and 2024 in years

    def test_year_has_year_field(self, client, seed):
        by_year = client.get("/api/performance").get_json()["by_year"]
        for row in by_year:
            assert "year" in row

    def test_sorted_ascending(self, client, seed):
        by_year = client.get("/api/performance").get_json()["by_year"]
        years = [r["year"] for r in by_year]
        assert years == sorted(years)


# ── By sector ─────────────────────────────────────────────────────────────────


class TestPerformanceBySector:
    def test_sector_present(self, client, seed):
        by_sector = client.get("/api/performance").get_json()["by_sector"]
        sectors = [r["sector"] for r in by_sector]
        assert "بنوك" in sectors

    def test_sector_has_sector_field(self, client, seed):
        by_sector = client.get("/api/performance").get_json()["by_sector"]
        for row in by_sector:
            assert "sector" in row

    def test_sorted_by_profit_factor_desc(self, client, seed):
        by_sector = client.get("/api/performance").get_json()["by_sector"]
        pfs = [r["profit_factor"] or 0 for r in by_sector]
        assert pfs == sorted(pfs, reverse=True)


# ── By version ────────────────────────────────────────────────────────────────


class TestPerformanceByVersion:
    def test_version_present(self, client, seed):
        by_version = client.get("/api/performance").get_json()["by_version"]
        versions = [r["version"] for r in by_version]
        assert "test_v1" in versions

    def test_version_has_version_field(self, client, seed):
        by_version = client.get("/api/performance").get_json()["by_version"]
        for row in by_version:
            assert "version" in row


# ── Top stocks ────────────────────────────────────────────────────────────────


class TestPerformanceTopStocks:
    def test_both_stocks_appear(self, client, seed):
        top = client.get("/api/performance").get_json()["top_stocks"]
        syms = [r["symbol"] for r in top]
        assert "COMI" in syms
        assert "FAISAL" in syms

    def test_top_stocks_have_required_fields(self, client, seed):
        top = client.get("/api/performance").get_json()["top_stocks"]
        for row in top:
            assert "symbol" in row
            assert "name_ar" in row

    def test_comi_better_than_faisal(self, client, seed):
        top = client.get("/api/performance").get_json()["top_stocks"]
        by_sym = {r["symbol"]: r for r in top}
        comi_pf   = by_sym["COMI"]["profit_factor"]  or 0
        faisal_pf = by_sym["FAISAL"]["profit_factor"] or 0
        assert comi_pf > faisal_pf
