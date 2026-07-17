"""Unit tests for the Trend Initiation Engine (v1)."""
import numpy as np
import pandas as pd
import pytest

from app.services.trend_engine import (
    detect_trend_initiation, TrendResult, PROFILES,
)


def _ohlcv(closes: np.ndarray, volume: float = 1_000_000.0) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "open":   closes,
        "high":   closes * 1.01,
        "low":    closes * 0.99,
        "close":  closes,
        "volume": np.full(n, volume),
    }, index=idx)


def _cross_df(volume: float = 1_000_000.0) -> pd.DataFrame:
    """
    Decline → strong rise, sliced so the LAST bar is a fresh EMA20/50 golden cross.
    Guarantees the primary entry condition deterministically.
    """
    dec = np.linspace(120.0, 95.0, 70)     # EMA20 falls below EMA50
    inc = np.linspace(95.0, 140.0, 50)     # strong rise → cross happens
    closes = np.concatenate([dec, inc])
    s = pd.Series(closes)
    e20 = s.ewm(span=20).mean()
    e50 = s.ewm(span=50).mean()
    cross = (e20 > e50) & (e20.shift(1) <= e50.shift(1))
    idxs = np.where(cross.values)[0]
    assert len(idxs) > 0, "helper failed to produce a cross"
    i = int(idxs[-1])
    closes = closes[: i + 1]
    assert len(closes) >= 60, "sliced df too short"
    return _ohlcv(closes, volume=volume)


class TestTrendInitiation:
    def test_fresh_cross_returns_signal(self):
        res = detect_trend_initiation(_cross_df(), ticker="TEST")
        assert isinstance(res, TrendResult)
        assert res.signal_family == "TREND"
        assert res.grade in ("A+", "A", "B")
        assert res.opp_type == f"TREND_{res.grade}"

    def test_no_cross_uptrend_returns_none(self):
        # steady uptrend from the start → cross is old, not on the last bar
        df = _ohlcv(np.linspace(90.0, 150.0, 100))
        assert detect_trend_initiation(df, ticker="TEST") is None

    def test_downtrend_returns_none(self):
        df = _ohlcv(np.linspace(150.0, 90.0, 100))
        assert detect_trend_initiation(df, ticker="TEST") is None

    def test_short_df_returns_none(self):
        df = _ohlcv(np.linspace(95.0, 110.0, 30))
        assert detect_trend_initiation(df, ticker="TEST") is None

    def test_low_liquidity_returns_none(self):
        # same valid cross but tiny volume → ADT below 3M floor
        df = _cross_df(volume=100.0)
        assert detect_trend_initiation(df, ticker="TEST") is None

    def test_breadth_floor_optional(self):
        df = _cross_df()
        # bear breadth + require_breadth → rejected
        assert detect_trend_initiation(df, breadth_pct=30.0, require_breadth=True) is None
        # bear breadth but floor off (default) → still signals
        assert detect_trend_initiation(df, breadth_pct=30.0, require_breadth=False) is not None

    def test_exit_levels_math(self):
        res = detect_trend_initiation(_cross_df(), ticker="TEST")
        entry = res.entry_price
        assert res.balanced_tp == pytest.approx(entry * (1 + PROFILES["BALANCED"]["tp_pct"] / 100), rel=1e-6)
        assert res.fast_tp == pytest.approx(entry * (1 + PROFILES["FAST"]["tp_pct"] / 100), rel=1e-6)
        # SL = entry - 2*ATR, identical for both profiles (same sl_atr)
        assert res.balanced_sl == res.fast_sl
        assert res.balanced_sl < entry

    def test_min_grade_filter(self):
        # requiring A+ should reject a plain-B setup (but our strong ramp is usually high ADX,
        # so just assert the filter returns None when the grade rank is below the floor)
        res_default = detect_trend_initiation(_cross_df(), min_grade="B", ticker="TEST")
        assert res_default is not None
        res_strict = detect_trend_initiation(_cross_df(), min_grade="A+", ticker="TEST")
        # either it clears A+ (strong trend) or it's filtered out — both are valid outcomes,
        # but if returned it must actually be A+
        if res_strict is not None:
            assert res_strict.grade == "A+"

    def test_feature_snapshot_shape(self):
        res = detect_trend_initiation(_cross_df(), ticker="TEST")
        snap = res.feature_snapshot()
        assert snap["signal_family"] == "TREND"
        assert snap["setup"] == "TREND_v1"
        assert "profiles" in snap and "BALANCED" in snap["profiles"]
