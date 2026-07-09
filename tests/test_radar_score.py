"""Unit tests for the Radar Score Engine."""
import pytest
from unittest.mock import MagicMock

from app.services.indicators import Indicators
from app.services.radar_score import (
    compute_radar_score, ScoreBreakdown,
    _trend_score, _momentum_score, _liquidity_score, _volume_score, _risk_penalty,
    REGIME_MULTIPLIERS,
)


def _make_indicators(**overrides) -> Indicators:
    defaults = dict(
        adx=30.0, plus_di=25.0, minus_di=15.0,
        ma20=100.0, ma50=95.0, ma200=90.0, price=105.0,
        rsi=60.0, macd=0.5, macd_signal=0.3, macd_hist=0.2,
        williams_r=-25.0, stoch_k=60.0, stoch_d=58.0,
        rvol=1.6, obv=1_000_000.0, obv_trend="UP",
        atr=1.5, atr_pct=1.43, bb_upper=110.0, bb_lower=90.0, bb_pct=0.75,
        data_quality="HIGH",
    )
    defaults.update(overrides)
    return Indicators(**defaults)


class TestTrendScore:
    def test_high_adx_gives_max(self):
        ind = _make_indicators(adx=45, price=110, ma20=105, ma50=100, macd_hist=0.5)
        score = _trend_score(ind)
        assert score == 20  # 20pts base + bonuses capped at 20

    def test_low_adx_gives_low_score(self):
        ind = _make_indicators(adx=10, price=80, ma20=90, ma50=95, macd_hist=-0.1)
        score = _trend_score(ind)
        assert score == 2

    def test_uptrend_alignment_bonus(self):
        ind_aligned = _make_indicators(adx=25, price=110, ma20=105, ma50=100, macd_hist=0.1)
        ind_flat    = _make_indicators(adx=25, price=98,  ma20=105, ma50=100, macd_hist=-0.1)
        assert _trend_score(ind_aligned) > _trend_score(ind_flat)


class TestMomentumScore:
    def test_sweet_spot_rsi(self):
        ind = _make_indicators(rsi=62, williams_r=-25, stoch_k=65, stoch_d=62)
        assert _momentum_score(ind) == 18

    def test_overbought_penalty(self):
        ind_normal = _make_indicators(rsi=60)
        ind_ob     = _make_indicators(rsi=78)
        assert _momentum_score(ind_normal) > _momentum_score(ind_ob)

    def test_oversold_low_score(self):
        # RSI=28 → base=0. Bonuses from williams_r and stoch can add up to 5 max.
        ind = _make_indicators(rsi=28, williams_r=-80, stoch_k=30, stoch_d=28)
        assert _momentum_score(ind) == 0


class TestLiquidityScore:
    def test_below_min_adt_is_zero(self):
        assert _liquidity_score(1_000_000) == 0

    def test_high_adt_max_score(self):
        assert _liquidity_score(200_000_000) == 16

    def test_medium_adt(self):
        score = _liquidity_score(50_000_000)
        assert score == 12


class TestVolumeScore:
    def test_high_rvol_obv_up_max(self):
        ind = _make_indicators(rvol=3.0, obv_trend="UP")
        assert _volume_score(ind) == 14

    def test_low_rvol_zero(self):
        ind = _make_indicators(rvol=0.5, obv_trend="DOWN")
        assert _volume_score(ind) == 0


class TestRiskPenalty:
    def test_high_atr_penalty(self):
        ind = _make_indicators(atr_pct=6.0, price=80, ma200=100, ma50=95, rsi=85)
        penalty = _risk_penalty(ind)
        assert penalty >= 10

    def test_low_risk_no_penalty(self):
        ind = _make_indicators(atr_pct=0.5, price=110, ma200=90, ma50=95, rsi=60)
        penalty = _risk_penalty(ind)
        assert penalty <= 2

    def test_penalty_capped_at_15(self):
        ind = _make_indicators(atr_pct=10.0, price=50, ma200=100, ma50=90, rsi=85)
        assert _risk_penalty(ind) <= 15


class TestComputeRadarScore:
    def test_returns_breakdown(self):
        ind = _make_indicators()
        bd  = compute_radar_score(ind, adt=50_000_000)
        assert isinstance(bd, ScoreBreakdown)

    def test_score_bounded(self):
        ind = _make_indicators()
        bd  = compute_radar_score(ind, adt=50_000_000)
        assert 0 <= bd.final_score <= 100

    def test_bull_regime_higher_than_bear(self):
        ind  = _make_indicators()
        bull = compute_radar_score(ind, adt=50_000_000, regime="BULL")
        bear = compute_radar_score(ind, adt=50_000_000, regime="BEAR")
        assert bull.final_score > bear.final_score

    def test_low_liquidity_returns_zero(self):
        ind = _make_indicators()
        bd  = compute_radar_score(ind, adt=500_000)
        assert bd.liquidity_score == 0

    def test_all_regime_multipliers_covered(self):
        ind = _make_indicators()
        for regime in REGIME_MULTIPLIERS:
            bd = compute_radar_score(ind, adt=30_000_000, regime=regime)
            assert 0 <= bd.final_score <= 100
