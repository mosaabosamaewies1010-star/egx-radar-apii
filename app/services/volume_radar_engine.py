"""
Volume Radar Engine v1.0 — EGX Radar
=====================================
يكشف أسهم دخلت فيها سيولة ذكية (VOL Expansion) خلال آخر 60 يوم
لكن لسه ما فيش تأكيد ترند — "راقب السهم"

وظيفته: Discovery فقط — مش إشارة شراء.
السهم ده هيتحول لـ Stage Breakout لما يجي الـ EMA cross.

Architecture (FROZEN v1.0):
  Stage Breakout  ⭐⭐⭐⭐⭐  Primary   — VOL سابق + TREND اليوم
  Trend Initiation⭐⭐⭐⭐   Secondary — TREND وحده (A+/A فقط)
  Volume Radar    ⭐⭐⭐      Discovery — VOL بدون TREND بعد

⚠️ FROZEN — لا تعدل المعاملات لمدة 6 شهور.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Constants (FROZEN v1.0) ────────────────────────────────────────────────────
VOL_LOOKBACK  = 60      # bars (FROZEN — same as Stage Engine)
VOL_RVOL_MIN  = 1.8    # minimum RVOL (FROZEN)
EMA_FAST      = 20
EMA_SLOW      = 50
MIN_ADT_EGP   = 3_000_000
MIN_ROWS      = EMA_SLOW + 10


# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class VolumeRadarResult:
    ticker:        str
    vol_age_bars:  int      # كام يوم من الـ VOL event لليوم
    vol_rvol:      float    # قوة الـ VOL spike
    vol_date:      str      # تاريخ الـ VOL event
    adt:           float    # average daily turnover (EGP/يوم)
    ema_fast:      float    # EMA20 الحالي
    ema_slow:      float    # EMA50 الحالي
    close:         float    # آخر سعر إغلاق
    watch_reasons: list[str] = field(default_factory=list)

    @property
    def opp_type(self) -> str:
        return "VOL_RADAR"

    @property
    def ema_gap_pct(self) -> float:
        """الفجوة بين EMA20 و EMA50 كنسبة مئوية — كلما قلت، كلما اقترب الـ cross"""
        if self.ema_slow <= 0:
            return 0.0
        return round((self.ema_slow - self.ema_fast) / self.ema_slow * 100, 2)

    def feature_snapshot(self) -> dict:
        return {
            "setup":         "VOL_RADAR_v1",
            "signal_family": "VOLUME",
            "vol_age_bars":  self.vol_age_bars,
            "vol_rvol":      round(self.vol_rvol, 2),
            "vol_date":      self.vol_date,
            "adt":           round(self.adt, 0),
            "ema_fast":      round(self.ema_fast, 4),
            "ema_slow":      round(self.ema_slow, 4),
            "close":         round(self.close, 4),
            "ema_gap_pct":   self.ema_gap_pct,
            "watch_reasons": self.watch_reasons,
        }


# ══════════════════════════════════════════════════════════════════════════════
# INDICATORS  (parity-exact with stage_engine.py)
# ══════════════════════════════════════════════════════════════════════════════

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span).mean()


def _adt(df: pd.DataFrame, window: int = 20) -> float:
    turnover = (df["close"] * df["volume"]).tail(window)
    return float(turnover.mean()) if not turnover.empty else 0.0


def _find_vol_spike(df: pd.DataFrame) -> Optional[tuple]:
    """
    Finds strongest VOL spike in last VOL_LOOKBACK bars (excluding today).
    Same detection logic as Stage Engine — RVOL ≥ 1.8 + close > prior 20-day max.
    Returns (age_bars, rvol, date_str) or None.
    """
    n = len(df)
    window_start = max(MIN_ROWS, n - 1 - VOL_LOOKBACK)
    window_end   = n - 2   # exclude today

    if window_start > window_end:
        return None

    close  = df["close"].values
    volume = df["volume"].values

    vol_ma          = pd.Series(volume).rolling(20).mean().values
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

def detect_volume_radar(
    df:     pd.DataFrame,
    adt:    Optional[float] = None,
    ticker: str = "",
) -> Optional[VolumeRadarResult]:
    """
    يرجع VolumeRadarResult لو:
      1. فيه VOL Expansion في آخر 60 يوم (نفس شرط Stage)
      2. EMA20 لسه تحت EMA50 — لو فوق فـ Stage Engine هو المسؤول
      3. سيولة كافية (ADT ≥ 3M جنيه/يوم)

    يُستدعى فقط لو ما فيش Stage أو Trend لنفس السهم اليوم.
    """
    if df is None or len(df) < MIN_ROWS + 5:
        return None

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            return None

    ema_fast_s   = _ema(df["close"], EMA_FAST)
    ema_slow_s   = _ema(df["close"], EMA_SLOW)
    ema_fast_val = float(ema_fast_s.iloc[-1])
    ema_slow_val = float(ema_slow_s.iloc[-1])

    # لو EMA20 فوق EMA50 → Stage Engine هو اللي يمسكه (أو Trend)، مش هنا
    if ema_fast_val >= ema_slow_val:
        return None

    # سيولة
    adt_val = adt if adt is not None else _adt(df)
    if adt_val < MIN_ADT_EGP:
        return None

    # VOL spike
    spike = _find_vol_spike(df)
    if spike is None:
        return None

    vol_age, vol_rvol, vol_date = spike
    weeks    = vol_age // 5
    gap_pct  = abs(ema_fast_val - ema_slow_val) / ema_slow_val * 100

    reasons = [
        f"📊 Volume Expansion منذ {vol_age} يوم (~{weeks} أسابيع) | RVOL={vol_rvol:.1f}×",
        f"⏳ EMA20 تحت EMA50 بفارق {gap_pct:.1f}% — لسه في مرحلة التجميع",
        f"👁️ راقب هذا السهم — محتمل Stage Breakout قادم",
    ]
    if vol_age <= 20:
        reasons.append("🔥 VOL حديث جداً — احتمال cross قريب")
    elif vol_age >= 45:
        reasons.append("⚡ دخل في النافذة المثالية (41-60 يوم)")

    if ticker:
        logger.debug(
            "VOL_RADAR[%s]: vol_age=%db rvol=%.1f ema_gap=%.1f%%",
            ticker, vol_age, vol_rvol, gap_pct,
        )

    return VolumeRadarResult(
        ticker        = ticker,
        vol_age_bars  = vol_age,
        vol_rvol      = round(vol_rvol, 2),
        vol_date      = vol_date,
        adt           = adt_val,
        ema_fast      = round(ema_fast_val, 4),
        ema_slow      = round(ema_slow_val, 4),
        close         = round(float(df["close"].iloc[-1]), 4),
        watch_reasons = reasons,
    )
