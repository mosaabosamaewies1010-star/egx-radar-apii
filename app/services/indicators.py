"""
Technical Indicators Engine
All indicators from the Quant Bible — computed from OHLCV DataFrame.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional


@dataclass
class Indicators:
    # Trend
    adx:       float
    plus_di:   float
    minus_di:  float
    ma20:      float
    ma50:      float
    ma200:     float
    price:     float   # latest close

    # Momentum
    rsi:       float
    macd:      float
    macd_signal: float
    macd_hist:   float
    williams_r:  float
    stoch_k:     float
    stoch_d:     float

    # Volume
    rvol:      float   # Relative Volume (vs 20-day avg)
    obv:       float
    obv_trend: str     # "UP" | "DOWN" | "FLAT"

    # Volatility
    atr:       float
    atr_pct:   float   # ATR / close * 100
    bb_upper:  float
    bb_lower:  float
    bb_pct:    float   # (close - lower) / (upper - lower)

    # Data
    data_quality: str  # HIGH | MEDIUM | LOW | NO_DATA

    # Intraday context (optional — default neutral so old call sites don't break)
    mf_ratio:  float = 0.0  # (2*close - high - low) / (high - low), range -1..1
    day_high:  float = 0.0  # last candle's high
    day_low:   float = 0.0  # last candle's low


def compute_indicators(df: pd.DataFrame, data_quality: str = "HIGH") -> Optional[Indicators]:
    """
    Compute all technical indicators from an OHLCV DataFrame.
    Returns None if insufficient data (< 30 rows).
    """
    if df is None or len(df) < 30:
        return None

    close  = df["close"].astype(float)
    high   = df["high"].astype(float)
    low    = df["low"].astype(float)
    volume = df["volume"].astype(float)
    price  = float(close.iloc[-1])

    # ── Moving Averages ───────────────────────────────────────────────
    ma20  = float(close.rolling(20).mean().iloc[-1])
    ma50  = float(close.rolling(50).mean().iloc[-1]) if len(df) >= 50  else ma20
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(df) >= 200 else ma50

    # ── RSI ───────────────────────────────────────────────────────────
    rsi = _rsi(close, 14)

    # ── MACD ──────────────────────────────────────────────────────────
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line   = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist_s = macd_line - signal_line

    macd       = float(macd_line.iloc[-1])
    macd_signal= float(signal_line.iloc[-1])
    macd_hist  = float(macd_hist_s.iloc[-1])

    # ── Williams %R ───────────────────────────────────────────────────
    period = 14
    highest = high.rolling(period).max()
    lowest  = low.rolling(period).min()
    wr = ((highest - close) / (highest - lowest + 1e-9) * -100).iloc[-1]
    williams_r = float(wr)

    # ── Stochastic (14, 3) ────────────────────────────────────────────
    stoch_k_raw = ((close - low.rolling(14).min()) /
                   (high.rolling(14).max() - low.rolling(14).min() + 1e-9) * 100)
    stoch_k = float(stoch_k_raw.rolling(3).mean().iloc[-1])
    stoch_d = float(stoch_k_raw.rolling(3).mean().rolling(3).mean().iloc[-1])

    # ── ATR ───────────────────────────────────────────────────────────
    tr   = _true_range(high, low, close)
    atr  = float(tr.rolling(14).mean().iloc[-1])
    atr_pct = (atr / price * 100) if price > 0 else 0.0

    # ── Bollinger Bands (20, 2) ───────────────────────────────────────
    bb_mid   = close.rolling(20).mean()
    bb_std   = close.rolling(20).std()
    bb_upper = float((bb_mid + 2 * bb_std).iloc[-1])
    bb_lower = float((bb_mid - 2 * bb_std).iloc[-1])
    bb_pct   = (price - bb_lower) / (bb_upper - bb_lower + 1e-9)

    # ── ADX ───────────────────────────────────────────────────────────
    adx, plus_di, minus_di = _adx(high, low, close, 14)

    # Intraday Money Flow: (2C - H - L) / (H - L), range -1..1
    day_h    = float(high.iloc[-1])
    day_l    = float(low.iloc[-1])
    denom    = day_h - day_l
    mf_ratio = (2 * price - day_h - day_l) / (denom + 1e-9) if denom > 1e-6 else 0.0

    avg_vol_20 = float(volume.rolling(20).mean().iloc[-1])
    cur_vol    = float(volume.iloc[-1])
    rvol = (cur_vol / avg_vol_20) if avg_vol_20 > 0 else 1.0

    # ── OBV ───────────────────────────────────────────────────────────
    obv        = _obv(close, volume)
    obv_trend  = _obv_trend(obv, window=5)

    return Indicators(
        adx=round(adx, 2),
        plus_di=round(plus_di, 2),
        minus_di=round(minus_di, 2),
        ma20=round(ma20, 4),
        ma50=round(ma50, 4),
        ma200=round(ma200, 4),
        price=round(price, 4),
        rsi=round(rsi, 2),
        macd=round(macd, 4),
        macd_signal=round(macd_signal, 4),
        macd_hist=round(macd_hist, 4),
        williams_r=round(williams_r, 2),
        stoch_k=round(stoch_k, 2),
        stoch_d=round(stoch_d, 2),
        rvol=round(rvol, 3),
        obv=round(float(obv.iloc[-1]), 0),
        obv_trend=obv_trend,
        atr=round(atr, 4),
        atr_pct=round(atr_pct, 3),
        bb_upper=round(bb_upper, 4),
        bb_lower=round(bb_lower, 4),
        bb_pct=round(float(bb_pct), 3),
        mf_ratio=round(float(mf_ratio), 3),
        day_high=round(day_h, 4),
        day_low=round(day_l, 4),
        data_quality=data_quality,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _rsi(close: pd.Series, period: int = 14) -> float:
    delta  = close.diff()
    gain   = delta.clip(lower=0).rolling(period).mean()
    loss   = (-delta.clip(upper=0)).rolling(period).mean()
    rs     = gain / (loss + 1e-9)
    rsi    = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    tr       = _true_range(high, low, close)
    atr      = tr.ewm(span=period, adjust=False).mean()

    up_move  = high.diff()
    dn_move  = -low.diff()

    plus_dm  = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)

    plus_di  = 100 * pd.Series(plus_dm,  index=high.index).ewm(span=period, adjust=False).mean() / (atr + 1e-9)
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(span=period, adjust=False).mean() / (atr + 1e-9)

    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx = dx.ewm(span=period, adjust=False).mean()

    return float(adx.iloc[-1]), float(plus_di.iloc[-1]), float(minus_di.iloc[-1])


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0))
    obv = (direction * volume).cumsum()
    return obv


def _obv_trend(obv: pd.Series, window: int = 5) -> str:
    if len(obv) < window + 1:
        return "FLAT"
    recent  = float(obv.iloc[-1])
    earlier = float(obv.iloc[-window])
    pct = (recent - earlier) / (abs(earlier) + 1e-9) * 100
    if pct >  2:  return "UP"
    if pct < -2:  return "DOWN"
    return "FLAT"
