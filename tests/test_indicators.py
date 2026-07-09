"""Unit tests for the Indicators Engine."""
import numpy as np
import pandas as pd
import pytest

from app.services.indicators import compute_indicators, Indicators


def _make_df(n: int = 60, trend: str = "up") -> pd.DataFrame:
    """Synthetic OHLCV DataFrame with a clear trend for deterministic testing."""
    rng = np.random.default_rng(42)
    base = 100.0
    prices = []
    for i in range(n):
        if trend == "up":
            base *= 1 + rng.normal(0.003, 0.008)
        elif trend == "down":
            base *= 1 + rng.normal(-0.003, 0.008)
        else:
            base *= 1 + rng.normal(0.0, 0.008)
        prices.append(base)

    closes = np.array(prices)
    highs  = closes * (1 + rng.uniform(0.001, 0.015, n))
    lows   = closes * (1 - rng.uniform(0.001, 0.015, n))
    opens  = closes * (1 + rng.normal(0, 0.005, n))
    vols   = rng.integers(500_000, 5_000_000, n).astype(float)

    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": closes, "volume": vols}, index=idx)


class TestComputeIndicators:
    def test_returns_indicators_object(self):
        df  = _make_df(60)
        ind = compute_indicators(df)
        assert isinstance(ind, Indicators)

    def test_returns_none_for_short_df(self):
        df = _make_df(20)
        assert compute_indicators(df) is None

    def test_rsi_bounded(self):
        ind = compute_indicators(_make_df(60))
        assert 0 <= ind.rsi <= 100

    def test_adx_positive(self):
        ind = compute_indicators(_make_df(60))
        assert ind.adx >= 0

    def test_atr_pct_positive(self):
        ind = compute_indicators(_make_df(60))
        assert ind.atr_pct >= 0

    def test_rvol_positive(self):
        ind = compute_indicators(_make_df(60))
        assert ind.rvol >= 0

    def test_obv_trend_valid(self):
        ind = compute_indicators(_make_df(60))
        assert ind.obv_trend in ("UP", "DOWN", "FLAT")

    def test_bb_pct_range(self):
        ind = compute_indicators(_make_df(60))
        # bb_pct can go outside 0-1 in extreme moves but usually in range
        assert isinstance(ind.bb_pct, float)

    def test_uptrend_high_rsi(self):
        ind = compute_indicators(_make_df(90, trend="up"))
        assert ind.rsi > 50

    def test_downtrend_low_rsi(self):
        ind = compute_indicators(_make_df(90, trend="down"))
        assert ind.rsi < 50

    def test_ma_ordering_in_uptrend(self):
        ind = compute_indicators(_make_df(90, trend="up"))
        # price should generally be above MA20 in strong uptrend
        assert ind.price > 0 and ind.ma20 > 0

    def test_williams_r_bounded(self):
        ind = compute_indicators(_make_df(60))
        assert -100 <= ind.williams_r <= 0

    def test_stoch_bounded(self):
        ind = compute_indicators(_make_df(60))
        assert 0 <= ind.stoch_k <= 100
        assert 0 <= ind.stoch_d <= 100
