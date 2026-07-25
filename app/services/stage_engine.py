"""
Stage Breakout Engine v1 — EGX Radar
=====================================
يكشف أسهم في "Stage 2 Revival": انفجار حجم حصل من 15-60 يوم تداول، ثم
golden cross يحصل اليوم — أعلى نقطة جودة في الـ Research.

Research basis (EGX backtest 2004-2026, n=632 إشارة في نافذة 60 يوم):
  Test PF FAST     = 2.075  (vs TREND وحده 1.644 | VOL وحده 1.346)
  Test PF BALANCED = 2.302

لماذا يعمل:
  VOL Expansion → السوق يلاحظ السهم ← smart money يدخل
  Cooling Period → ضعيف الأيدي يخرج ← تجميع هادئ
  EMA cross اليوم → ترند مؤسسي جديد ← أفضل نقطة دخول

⚠️ لا يُعدّل هنا بدون walk-forward جديد.
⚠️ يجب أن يتطابق حساب المؤشرات مع backtest (rotation_analysis.py).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
EMA_FAST      = 20
EMA_SLOW      = 50
ADX_PERIOD    = 14
RSI_PERIOD    = 14
ATR_PERIOD    = 14
MIN_ADT_EGP   = 3_000_000
MIN_ROWS      = EMA_SLOW + 10
VOL_LOOKBACK  = 60      # bars — sweet spot validated (PF Test 2.075)
VOL_RVOL_MIN  = 1.8     # minimum RVOL for a qualifying VOL spike
SCORE_STRONG  = 80
SCORE_DEVELOPING = 60

PROFILES = {
    "FAST":     {"tp_pct": 7.0,  "sl_atr": 2.0, "max_bars": 5},
    "BALANCED": {"tp_pct": 15.0, "sl_atr": 2.0, "max_bars": 10},
}


# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class StageResult:
    ticker:        str
    signal_family: str     # "STAGE"
    strength:      str     # "STRONG" | "DEVELOPING"
    stage_score:   float   # 0-100

    adx:           float
    rsi:           float
    ema_fast:      float
    ema_slow:      float
    adt:           float
    atr:           float

    # VOL event that preceded this cross
    vol_age_bars:  int     # how many bars ago the best VOL spike happened
    vol_rvol:      float   # RVOL at that spike
    vol_date:      str     # date of the spike

    entry_price:       float
    fast_tp:           float
    fast_sl:           float
    fast_max_bars:     int
    balanced_tp:       float
    balanced_sl:       float
    balanced_max_bars: int

    reasons: list[str] = field(default_factory=list)

    @property
    def opp_type(self) -> str:
        return f"STAGE_{self.strength}"

    def feature_snapshot(self) -> dict:
        return {
            "setup":         "STAGE_v1",
            "signal_family": "STAGE",
            "strength":      self.strength,
            "stage_score":   round(self.stage_score, 1),
            "adx":           round(self.adx, 1),
            "rsi":           round(self.rsi, 1),
            "ema_fast":      round(self.ema_fast, 4),
            "ema_slow":      round(self.ema_slow, 4),
            "adt":           round(self.adt, 0),
            "atr":           round(self.atr, 4),
            "vol_age_bars":  self.vol_age_bars,
            "vol_rvol":      round(self.vol_rvol, 2),
            "vol_date":      self.vol_date,
            "reasons":       self.reasons,
            "profiles": {
                "FAST":     {
                    "tp":       self.fast_tp,
                    "sl":       self.fast_sl,
                    "max_bars": self.fast_max_bars,
                },
                "BALANCED": {
                    "tp":       self.balanced_tp,
                    "sl":       self.balanced_sl,
                    "max_bars": self.balanced_max_bars,
                },
            },
        }


# ══════════════════════════════════════════════════════════════════════════════
# INDICATORS  (parity-exact with trend_engine + research backtest)
# ══════════════════════════════════════════════════════════════════════════════

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span).mean()


def _rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    return 100 - 100 / (1 + gain / (loss + 1e-9))


def _atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"]  - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat([
        high - low, (high - prev).abs(), (low - prev).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    up, dn = high.diff(), -low.diff()
    plus_dm  = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=high.index)
    plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / (atr + 1e-9)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / (atr + 1e-9)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    return dx.ewm(span=period, adjust=False).mean()


def _adt(df: pd.DataFrame, window: int = 20) -> float:
    turnover = (df["close"] * df["volume"]).tail(window)
    return float(turnover.mean()) if not turnover.empty else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# STAGE SCORE  (max = 10/20/30 + 15/25/30 + 15/25/30 + 5/10 = 100)
# ══════════════════════════════════════════════════════════════════════════════

def _stage_score(vol_age: int, vol_rvol: float, adx: float, adt: float) -> float:
    score = 0.0

    # 1. VOL age — ideal window is 41-60 bars (1-3 months, validated)
    if vol_age <= 20:
        score += 10
    elif vol_age <= 40:
        score += 20
    else:
        score += 30     # sweet spot: 41-60 bars

    # 2. ADX strength at the cross
    if adx >= 30:
        score += 30
    elif adx >= 25:
        score += 25
    else:
        score += 15     # 20-25 minimum

    # 3. RVOL intensity at the VOL spike
    if vol_rvol >= 4.0:
        score += 30
    elif vol_rvol >= 2.5:
        score += 25
    else:
        score += 15     # 1.8-2.5 minimum

    # 4. Liquidity bonus
    if adt >= 10_000_000:
        score += 10
    elif adt >= MIN_ADT_EGP:
        score += 5

    return min(100.0, score)


# ══════════════════════════════════════════════════════════════════════════════
# VOL SPIKE SEARCH
# ══════════════════════════════════════════════════════════════════════════════

def _best_vol_spike(df: pd.DataFrame, lookback: int = VOL_LOOKBACK):
    """
    Finds the strongest VOL spike in the last `lookback` bars (excluding today).
    Conditions: RVOL >= VOL_RVOL_MIN AND close > prior 20-day max of close.
    Returns (age_in_bars, rvol, date_str) or None.
    """
    n = len(df)
    window_start = max(MIN_ROWS, n - 1 - lookback)
    window_end   = n - 2   # exclude today

    if window_start > window_end:
        return None

    close  = df["close"].values
    volume = df["volume"].values

    # 20-bar rolling mean of volume (vectorised)
    vol_ma = pd.Series(volume).rolling(20).mean().values
    # prior 20-day max of close (matches backtest formula exactly)
    prior_close_max = pd.Series(close).shift(1).rolling(20).max().values

    best_rvol = 0.0
    best_idx  = None

    for i in range(window_start, window_end + 1):
        if vol_ma[i] <= 0 or np.isnan(vol_ma[i]):
            continue
        if np.isnan(prior_close_max[i]):
            continue
        rvol = volume[i] / vol_ma[i]
        if rvol >= VOL_RVOL_MIN and close[i] > prior_close_max[i] and rvol > best_rvol:
            best_rvol = rvol
            best_idx  = i

    if best_idx is None:
        return None

    age = (n - 1) - best_idx
    try:
        date_str = pd.Timestamp(df.index[best_idx]).strftime('%Y-%m-%d')
    except Exception:
        date_str = str(best_idx)

    return age, best_rvol, date_str


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def detect_stage_breakout(
    df:          pd.DataFrame,
    breadth_pct: float = 50.0,
    adt:         Optional[float] = None,
    ticker:      str = "",
) -> Optional[StageResult]:
    """
    يفحص DataFrame لسهم واحد ويرجع StageResult لو فيه Stage Breakout، أو None.

    Parameters
    ----------
    df          : OHLCV مرتّب تصاعدياً، أعمدة open/high/low/close/volume
    breadth_pct : % الأسهم فوق EMA50 (سياق فقط)
    adt         : Average Daily Turnover؛ لو None بيتحسب داخلياً
    ticker      : اسم السهم للـ logging
    """
    if df is None or len(df) < MIN_ROWS + 5:
        return None

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            return None

    ema_fast = _ema(df["close"], EMA_FAST)
    ema_slow = _ema(df["close"], EMA_SLOW)

    # 1) Fresh golden cross — exactly the same condition as trend_engine
    fresh_cross = (
        ema_fast.iloc[-1]  > ema_slow.iloc[-1]
        and ema_fast.iloc[-2] <= ema_slow.iloc[-2]
    )
    if not fresh_cross:
        return None

    # 2) ADX >= 20
    adx_val = float(_adx(df).iloc[-1])
    if np.isnan(adx_val) or adx_val < 20.0:
        return None

    # 3) RSI > 50
    rsi_val = float(_rsi(df["close"]).iloc[-1])
    if np.isnan(rsi_val) or rsi_val <= 50.0:
        return None

    # 4) Liquidity
    adt_val = adt if adt is not None else _adt(df)
    if adt_val < MIN_ADT_EGP:
        return None

    # 5) Find strongest VOL spike in last 60 bars
    spike = _best_vol_spike(df, lookback=VOL_LOOKBACK)
    if spike is None:
        logger.debug("STAGE[%s]: cross OK but no VOL spike in last %d bars", ticker, VOL_LOOKBACK)
        return None

    vol_age, vol_rvol, vol_date = spike

    # 6) Stage Score
    score = _stage_score(vol_age, vol_rvol, adx_val, adt_val)
    if score < SCORE_DEVELOPING:
        return None

    strength = "STRONG" if score >= SCORE_STRONG else "DEVELOPING"

    entry   = float(df["close"].iloc[-1])
    atr_raw = float(_atr(df).iloc[-1])
    atr_val = atr_raw if not np.isnan(atr_raw) and atr_raw > 0 else entry * 0.02

    fast_p, bal_p = PROFILES["FAST"], PROFILES["BALANCED"]

    weeks_str = f"{vol_age // 5:.0f} أسابيع" if vol_age >= 5 else "أيام"
    icon = "🔥" if strength == "STRONG" else "⚡"

    reasons = [
        f"{icon} Stage Score: {score:.0f}/100 — {strength}",
        f"🚀 Golden cross EMA{EMA_FAST}/{EMA_SLOW} — بداية ترند جديد اليوم",
        f"📊 Volume Expansion منذ {vol_age} يوم (~{weeks_str}) | RVOL={vol_rvol:.1f}× | تاريخ الاندفاع: {vol_date}",
        f"✅ ADX={adx_val:.0f} — قوة الترند مؤكدة",
        f"✅ RSI={rsi_val:.0f} — زخم إيجابي",
    ]
    if adt_val >= 10_000_000:
        reasons.append(f"💧 سيولة عالية ({adt_val / 1e6:.0f}M ج/يوم)")

    result = StageResult(
        ticker            = ticker,
        signal_family     = "STAGE",
        strength          = strength,
        stage_score       = round(score, 1),
        adx               = round(adx_val, 2),
        rsi               = round(rsi_val, 2),
        ema_fast          = round(float(ema_fast.iloc[-1]), 4),
        ema_slow          = round(float(ema_slow.iloc[-1]), 4),
        adt               = adt_val,
        atr               = round(atr_val, 4),
        vol_age_bars      = vol_age,
        vol_rvol          = round(vol_rvol, 2),
        vol_date          = vol_date,
        entry_price       = round(entry, 4),
        fast_tp           = round(entry * (1 + fast_p["tp_pct"] / 100), 4),
        fast_sl           = round(entry - fast_p["sl_atr"] * atr_val, 4),
        fast_max_bars     = fast_p["max_bars"],
        balanced_tp       = round(entry * (1 + bal_p["tp_pct"] / 100), 4),
        balanced_sl       = round(entry - bal_p["sl_atr"] * atr_val, 4),
        balanced_max_bars = bal_p["max_bars"],
        reasons           = reasons,
    )

    if ticker:
        logger.info(
            "STAGE[%s]: %s score=%.0f adx=%.0f vol_age=%db rvol=%.1f",
            ticker, result.opp_type, score, adx_val, vol_age, vol_rvol,
        )
    return result
