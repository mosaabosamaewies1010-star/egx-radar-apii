"""
SRA Engine — Smart Recovery Accumulation
==========================================
العقل الجديد للبحث عن الفرص.

الفلسفة:
  ليس "سهم قوي يصعد"
  بل "سهم انتهى بيعه وبدأت السيولة الذكية تدخل عند منطقة خوف"

المعادلة الأساسية:
  SWING_LOW + RVOL_SPIKE_AFTER = نقطة دخول محتملة
  SRA Score v2 = قوة الإعداد (0-100)
  Grade A+/A/B = مستوى الثقة

Exit Profiles:
  FAST:     TP 7%  | SL 2×ATR | Max 5 bars
  BALANCED: TP 15% | SL 2×ATR | Max 10 bars

يُستدعى من daily_scan.py — لا يمس الـ radar القديم.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
SWING_LOOKBACK  = 5     # bars each side for swing low detection
SCAN_WINDOW     = 10    # how many recent bars to scan
RVOL_THRESHOLD  = 1.5   # minimum spike multiplier
RVOL_WINDOW     = 3     # bars after swing to check RVOL

# Exit profiles — frozen from Walk Forward validation
PROFILES = {
    "FAST":     {"tp_pct": 7.0,  "sl_atr": 2.0, "max_bars": 5},
    "BALANCED": {"tp_pct": 15.0, "sl_atr": 2.0, "max_bars": 10},
}


# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SRAResult:
    """
    نتيجة فحص سهم واحد.
    تُحفظ في Opportunity مع feature_snapshot كامل.
    """
    ticker:        str
    setup_type:    str        # "SRA"
    grade:         str        # "A+" | "A" | "B"
    score:         float      # 0-100

    # Signal quality
    rvol_spike:    float      # RVOL peak in first 3 bars after swing
    rsi_at_low:    float
    market_breadth: float     # 0-100%
    regime:        str        # bear | bull | neutral
    sector_slope_positive: bool

    # Entry levels
    entry_price:   float
    swing_low:     float

    # FAST profile
    fast_tp:       float
    fast_sl:       float
    fast_max_bars: int

    # BALANCED profile
    balanced_tp:   float
    balanced_sl:   float
    balanced_max_bars: int

    # Context
    atr:           float
    signals:       list[str]  = field(default_factory=list)

    # Historical confidence (injected after lookup)
    similar_cases:      int   = 0
    historical_win_rate: float = 0.0
    avg_return:         float = 0.0

    @property
    def opp_type(self) -> str:
        """للـ DB: يُخزَّن في حقل opp_type."""
        return f"SRA_{self.grade}"

    def feature_snapshot(self) -> dict:
        """كل السياق — يُحفظ في feature_snapshot JSON كـ Decision Moat."""
        return {
            "setup":                  "SRA_v2",
            "sra_score":              self.score,
            "sra_grade":              self.grade,
            "rvol_spike":             round(self.rvol_spike, 2),
            "rsi_at_low":             round(self.rsi_at_low, 1),
            "market_breadth_pct":     round(self.market_breadth, 1),
            "regime":                 self.regime,
            "sector_slope_positive":  self.sector_slope_positive,
            "swing_low":              round(self.swing_low, 4),
            "atr":                    round(self.atr, 4),
            "signals":                self.signals,
            "similar_cases":          self.similar_cases,
            "historical_win_rate":    round(self.historical_win_rate, 1),
            "avg_return":             round(self.avg_return, 2),
            "profiles": {
                "FAST":     {"tp": self.fast_tp,     "sl": self.fast_sl,     "max_bars": self.fast_max_bars},
                "BALANCED": {"tp": self.balanced_tp, "sl": self.balanced_sl, "max_bars": self.balanced_max_bars},
            },
        }


# ══════════════════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════════════════

def _compute_rvol(vol: pd.Series, window: int = 20) -> pd.Series:
    return vol / (vol.rolling(window).mean() + 1e-10)


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).rolling(period).mean()
    l = (-d.clip(upper=0)).rolling(period).mean()
    return 100 - 100 / (1 + g / (l + 1e-10))


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"]  - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ══════════════════════════════════════════════════════════════════════════════
# DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _detect_recent_swing_lows(df: pd.DataFrame) -> list[int]:
    """
    يكتشف قيعان محلية حديثة.
    المعيار المزدوج:
      1. يكون أدنى نقطة في النافذة المحيطة (lookback bars من كل جانب)
      2. يكون في أدنى 30% من آخر 10 بارات (is_recent_low)
    """
    n      = len(df)
    swings = []
    lb     = SWING_LOOKBACK
    start  = max(lb, n - SCAN_WINDOW)

    for i in range(start, n - lb):
        window_low = df["low"].iloc[i - lb: i + lb + 1]
        if df["low"].iloc[i] != window_low.min():
            continue
        if df["low"].iloc[i] >= df["low"].iloc[i - 1]:
            continue
        if df["low"].iloc[i] >= df["low"].iloc[i + 1]:
            continue

        prev10 = df["low"].iloc[max(0, i - 10): i]
        if len(prev10) >= 3 and df["low"].iloc[i] <= float(prev10.quantile(0.30)):
            swings.append(i)

    return swings


def _has_rvol_spike(rvol: pd.Series, sl_idx: int) -> tuple[bool, float]:
    """يتحقق من RVOL spike في الـ bars بعد القاع مباشرة."""
    post = rvol.iloc[sl_idx + 1: sl_idx + RVOL_WINDOW + 1]
    if post.empty:
        return False, 0.0
    peak = float(post.max())
    return peak >= RVOL_THRESHOLD, round(peak, 2)


# ══════════════════════════════════════════════════════════════════════════════
# SRA SCORE v2
# ══════════════════════════════════════════════════════════════════════════════

def _compute_sra_score(
    df:              pd.DataFrame,
    sl_idx:          int,
    rvol_series:     pd.Series,
    rvol_spike:      bool,
    rvol_value:      float,
    regime:          str,
    sector_positive: bool,
) -> tuple[float, str, list[str]]:
    """
    SRA Score v2 — مجمّد من Walk Forward Validation.
    الأوزان:
      SwingLow  25 | RVOL     35 | Regime 15/10/0
      Sector     8 | RSI   8/3/-5 | Dry Vol 3
      OBV        2 | Support  4
    """
    score   = 25.0
    signals = ["Swing Low confirmed (+25)"]

    # RVOL
    if rvol_spike:
        score += 35
        signals.append(f"Volume spike +{rvol_value:.0%} of avg (+35)")

    # Regime
    regime_pts = {"bear": 15, "bull": 10, "neutral": 0}.get(regime, 0)
    if regime_pts:
        score += regime_pts
        signals.append(f"Market {regime.upper()} (+{regime_pts})")

    # Sector
    if sector_positive:
        score += 8
        signals.append("Sector rising (+8)")

    # RSI
    rsi_series = _compute_rsi(df["close"])
    rsi_val    = float(rsi_series.iloc[sl_idx])
    if rsi_val < 25:
        score -= 5
        signals.append(f"RSI {rsi_val:.0f} — broken stock (-5)")
    elif rsi_val < 35:
        score += 8
        signals.append(f"RSI {rsi_val:.0f} — sweet spot (+8)")
    elif rsi_val < 45:
        score += 3
        signals.append(f"RSI {rsi_val:.0f} — mild oversold (+3)")

    # Dry Volume (volume drying before swing)
    rvol_before = rvol_series.iloc[max(0, sl_idx - 10): sl_idx]
    if len(rvol_before) >= 3 and (rvol_before < 0.7).any():
        score += 3
        signals.append("Dry volume before swing (+3)")

    score = max(0.0, min(100.0, score))

    if score >= 78 and rvol_spike:
        grade = "A+"
    elif score >= 60 and rvol_spike:
        grade = "A"
    elif rvol_spike:
        grade = "B"
    else:
        grade = "C"

    return round(score, 1), grade, signals


# ══════════════════════════════════════════════════════════════════════════════
# MARKET BREADTH  (SRA-compatible)
# ══════════════════════════════════════════════════════════════════════════════

def compute_sra_breadth(all_dfs: dict[str, pd.DataFrame]) -> tuple[str, float]:
    """
    يحسب Regime و Breadth% من % الأسهم فوق EMA50.
    متوافق مع الـ Walk Forward Validation.

    يرجع: (regime, breadth_pct)
    """
    above, total = 0, 0
    for df in all_dfs.values():
        if len(df) < 50:
            continue
        ema = df["close"].ewm(span=50).mean()
        total += 1
        if float(df["close"].iloc[-1]) > float(ema.iloc[-1]):
            above += 1
    if total == 0:
        return "neutral", 50.0
    pct = above / total * 100
    regime = "bull" if pct >= 60 else ("bear" if pct <= 35 else "neutral")
    return regime, round(pct, 1)


def compute_sector_slope(peer_dfs: list[pd.DataFrame]) -> float:
    """يحسب متوسط انحدار EMA50 للقطاع."""
    slopes = []
    for df in peer_dfs:
        if len(df) < 55:
            continue
        ema = df["close"].ewm(span=50).mean()
        slopes.append((float(ema.iloc[-1]) - float(ema.iloc[-6])) / (float(ema.iloc[-6]) + 1e-10))
    return float(np.mean(slopes)) if slopes else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def detect_sra_setup(
    df:              pd.DataFrame,
    regime:          str,
    breadth_pct:     float,
    sector_positive: bool,
    min_grade:       str = "B",
) -> Optional[SRAResult]:
    """
    يفحص DataFrame لسهم واحد ويرجع أفضل SRA setup حديث، أو None.

    Parameters
    ----------
    df              : OHLCV DataFrame — مرتّب تصاعدياً، أعمدة: open/high/low/close/volume
    regime          : "bull" | "bear" | "neutral"
    breadth_pct     : 0-100
    sector_positive : هل الـ EMA50 للقطاع في اتجاه صاعد؟
    min_grade       : الحد الأدنى للـ Grade المقبول
    """
    if df is None or len(df) < 60:
        return None

    grade_rank = {"A+": 3, "A": 2, "B": 1, "C": 0}
    min_rank   = grade_rank.get(min_grade, 1)

    # ── Normalize column names ───────────────────────────────────────────────
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            return None

    rvol_series = _compute_rvol(df["volume"])
    atr_series  = _compute_atr(df)

    swing_idxs = _detect_recent_swing_lows(df)
    if not swing_idxs:
        return None

    best: Optional[SRAResult] = None

    for sl_idx in swing_idxs:
        has_spike, rvol_val = _has_rvol_spike(rvol_series, sl_idx)
        if not has_spike:
            continue

        score, grade, signals = _compute_sra_score(
            df, sl_idx, rvol_series, has_spike, rvol_val,
            regime, sector_positive,
        )

        if grade_rank.get(grade, 0) < min_rank:
            continue

        rsi_val    = float(_compute_rsi(df["close"]).iloc[sl_idx])
        atr_val    = float(atr_series.iloc[sl_idx]) if not np.isnan(atr_series.iloc[sl_idx]) else float(df["close"].iloc[sl_idx]) * 0.02
        swing_low  = float(df["low"].iloc[sl_idx])
        entry      = round(float(df["close"].iloc[sl_idx]) * 1.002, 4)

        fast_p     = PROFILES["FAST"]
        balanced_p = PROFILES["BALANCED"]

        result = SRAResult(
            ticker                = "",   # يُضاف خارجياً
            setup_type            = "SRA",
            grade                 = grade,
            score                 = score,
            rvol_spike            = rvol_val,
            rsi_at_low            = round(rsi_val, 1),
            market_breadth        = breadth_pct,
            regime                = regime,
            sector_slope_positive = sector_positive,
            entry_price           = entry,
            swing_low             = swing_low,
            fast_tp               = round(entry * (1 + fast_p["tp_pct"] / 100), 4),
            fast_sl               = round(entry - fast_p["sl_atr"] * atr_val, 4),
            fast_max_bars         = fast_p["max_bars"],
            balanced_tp           = round(entry * (1 + balanced_p["tp_pct"] / 100), 4),
            balanced_sl           = round(entry - balanced_p["sl_atr"] * atr_val, 4),
            balanced_max_bars     = balanced_p["max_bars"],
            atr                   = round(atr_val, 4),
            signals               = signals,
        )

        if best is None or score > best.score:
            best = result

    return best
