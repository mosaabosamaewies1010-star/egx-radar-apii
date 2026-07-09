"""Unit tests for the Opportunity Engine."""
import pytest

from app.services.indicators import Indicators
from app.services.radar_score import ScoreBreakdown
from app.services.opportunity import compute_opportunity, MIN_RR_RATIO


def _ind(**kw) -> Indicators:
    defaults = dict(
        adx=32.0, plus_di=26.0, minus_di=14.0,
        ma20=100.0, ma50=95.0, ma200=90.0, price=105.0,
        rsi=63.0, macd=0.5, macd_signal=0.3, macd_hist=0.2,
        williams_r=-20.0, stoch_k=65.0, stoch_d=62.0,
        rvol=1.8, obv=1_000_000.0, obv_trend="UP",
        atr=1.5, atr_pct=1.43, bb_upper=112.0, bb_lower=92.0, bb_pct=0.65,
        data_quality="HIGH",
    )
    defaults.update(kw)
    return Indicators(**defaults)


def _bd(score: float = 75.0) -> ScoreBreakdown:
    return ScoreBreakdown(
        trend_score=16, momentum_score=15, liquidity_score=12,
        volume_score=12, sector_score=10, fundamental_score=10,
        risk_penalty=2, regime_multiplier=1.0,
        raw_score=75, final_score=score,
    )


class TestComputeOpportunity:
    def test_returns_result_for_high_score(self):
        result = compute_opportunity(_ind(), _bd(75))
        assert result is not None

    def test_returns_none_for_low_score(self):
        result = compute_opportunity(_ind(), _bd(55))
        assert result is None

    def test_rr_ratio_above_min(self):
        result = compute_opportunity(_ind(), _bd(75))
        assert result.rr_ratio >= MIN_RR_RATIO

    def test_tp1_above_entry(self):
        result = compute_opportunity(_ind(), _bd(75))
        assert result.tp1_price > result.entry_price

    def test_tp2_above_tp1(self):
        result = compute_opportunity(_ind(), _bd(75))
        assert result.tp2_price > result.tp1_price

    def test_sl_below_entry(self):
        result = compute_opportunity(_ind(), _bd(75))
        assert result.sl_price < result.entry_price

    def test_sharia_type_for_sharia_stock(self):
        high_ind = _ind(adx=20, rvol=1.0, macd_hist=-0.1)  # not breakout conditions
        result = compute_opportunity(high_ind, _bd(75), is_sharia=True)
        if result:
            assert result.opp_type == "Sharia"

    def test_breakout_conditions(self):
        brk_ind = _ind(adx=35, rvol=2.0, macd_hist=0.5)
        result  = compute_opportunity(brk_ind, _bd(80))
        assert result is not None
        assert result.opp_type == "Breakout"

    def test_max_hold_days_positive(self):
        result = compute_opportunity(_ind(), _bd(75))
        assert result.max_hold_days > 0

    def test_signal_quality_high_for_strong_score(self):
        ind    = _ind(rvol=2.0)
        result = compute_opportunity(ind, _bd(85))
        assert result is not None
        assert result.signal_quality == "HIGH"
