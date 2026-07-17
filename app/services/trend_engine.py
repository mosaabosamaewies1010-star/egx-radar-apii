"""
Trend Initiation Engine v1 — EGX Radar
======================================
PRIMARY signal engine, chosen by the Research Journal (docs/research/, 2026-07-17).
Signal family: "TREND".

الفلسفة (بعد بحث كامل):
  مش "score عالي" ولا "مؤشرات كتير" — بل التقاط **بداية** الترند.
  البحث أثبت: كل ما زادت الطبقات، الـ edge قلّ. والـ radar_score علاقته
  بالعائد مقلوبة (score أعلى = دخول متأخر = أسوأ).

القاعدة (V1 — المتحقّقة out-of-sample، net PF ≈ 1.42؛ 2025=1.32، 2026=1.81):
  1. EMA20 يعبر EMA50 لأعلى في آخر شمعة   (fresh golden cross)
  2. ADX(14) >= 20                          (تأكيد وجود اتجاه)
  3. RSI(14) > 50                           (زخم إيجابي)
  4. سيولة: ADT >= 3M جنيه                  (RVOL/إشارة بلا سيولة = ضوضاء)
  5. breadth > 35% (اختياري — هامشي، مطفي افتراضياً)

⚠️ متعمّد إنه بسيط. ممنوع تضيف هنا: Radar Score / MACD / Ichimoku / Stochastic /
   Volume score — البحث أثبت إنهم بيعكسوا/بيميّعوا الـ edge. أي إضافة لازم تعدّي
   Walk-Forward الأول (شوف docs/research/experiments/Momentum_Sweep.md).

⚠️ Parity: حساب المؤشرات هنا لازم يطابق الـ research backtest (walk_forward.py)
   عشان production == research. أي اختلاف = parity bug يتصلّح قبل الإطلاق.

Exit profiles (مجمّدة من Walk-Forward، نفس SRA):
  FAST     : TP 7%  | SL 2×ATR | 5 bars
  BALANCED : TP 15% | SL 2×ATR | 10 bars
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
EMA_FAST      = 20
EMA_SLOW      = 50
ADX_PERIOD    = 14
ADX_MIN       = 20.0
RSI_PERIOD    = 14
RSI_MIN       = 50.0
ATR_PERIOD    = 14
MIN_ADT_EGP   = 3_000_000    # سيولة دنيا — تحت كده الإشارة ضوضاء
BREADTH_MIN   = 35.0         # فلتر اختياري (bear floor)
MIN_ROWS      = EMA_SLOW + 10

# Exit profiles — mirror sra_engine.PROFILES (frozen from Walk-Forward validation)
PROFILES = {
    "FAST":     {"tp_pct": 7.0,  "sl_atr": 2.0, "max_bars": 5},
    "BALANCED": {"tp_pct": 15.0, "sl_atr": 2.0, "max_bars": 10},
}

_GRADE_RANK = {"A+": 3, "A": 2, "B": 1, "C": 0}


# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TrendResult:
    ticker:         str
    signal_family:  str        # "TREND"
    grade:          str        # "A+" | "A" | "B"
    trend_strength: float      # 0-100 — display/confidence only, NOT a gate

    # Context
    adx:            float
    rsi:            float
    ema_fast:       float
    ema_slow:       float
    market_breadth: float
    adt:            float

    # Entry levels
    entry_price:    float
    atr:            float

    # FAST profile
    fast_tp:        float
    fast_sl:        float
    fast_max_bars:  int

    # BALANCED profile
    balanced_tp:       float
    balanced_sl:       float
    balanced_max_bars: int

    reasons:        list[str] = field(default_factory=list)

    # Historical confidence (injected after KB lookup — same pattern as SRA)
    similar_cases:       int   = 0
    historical_win_rate: float = 0.0
    avg_return:          float = 0.0

    @property
    def opp_type(self) -> str:
        return f"TREND_{self.grade}"

    def feature_snapshot(self) -> dict:
        return {
            "setup":              "TREND_v1",
            "signal_family":      "TREND",
            "grade":              self.grade,
            "trend_strength":     round(self.trend_strength, 1),
            "adx":                round(self.adx, 1),
            "rsi":                round(self.rsi, 1),
            "ema_fast":           round(self.ema_fast, 4),
            "ema_slow":           round(self.ema_slow, 4),
            "market_breadth_pct": round(self.market_breadth, 1),
            "adt":                round(self.adt, 0),
            "atr":                round(self.atr, 4),
            "reasons":            self.reasons,
            "similar_cases":       self.similar_cases,
            "historical_win_rate": round(self.historical_win_rate, 1),
            "avg_return":          round(self.avg_return, 2),
            "profiles": {
                "FAST":     {"tp": self.fast_tp,     "sl": self.fast_sl,     "max_bars": self.fast_max_bars},
                "BALANCED": {"tp": self.balanced_tp, "sl": self.balanced_sl, "max_bars": self.balanced_max_bars},
            },
        }


# ══════════════════════════════════════════════════════════════════════════════
# INDICATORS  (parity-exact with research backtest — do not "improve" casually)
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
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
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


def _grade_from_adx(adx: float) -> str:
    if adx >= 30:
        return "A+"
    if adx >= 25:
        return "A"
    return "B"          # ADX ≥ 20 دخل أصلاً


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def detect_trend_initiation(
    df:              pd.DataFrame,
    breadth_pct:     float = 50.0,
    adt:             Optional[float] = None,
    min_grade:       str = "B",
    ticker:          str = "",
    require_breadth: bool = False,
) -> Optional[TrendResult]:
    """
    يفحص DataFrame لسهم واحد ويرجع TrendResult لو النهاردة فيه بداية ترند، أو None.

    Parameters
    ----------
    df              : OHLCV مرتّب تصاعدياً، أعمدة open/high/low/close/volume
    breadth_pct     : 0-100 — % الأسهم فوق EMA50 (للفلتر الاختياري وللسياق)
    adt             : Average Daily Turnover بالجنيه؛ لو None بيتحسب داخلياً
    min_grade       : أدنى grade مقبول ("B" افتراضياً)
    ticker          : اسم السهم للـ logging
    require_breadth : لو True، يرفض الإشارة لما breadth <= 35% (bear floor)
    """
    if df is None or len(df) < MIN_ROWS:
        if ticker:
            logger.debug("TREND[%s]: skipped — %d rows (need %d)",
                         ticker, len(df) if df is not None else 0, MIN_ROWS)
        return None

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            if ticker:
                logger.debug("TREND[%s]: missing column '%s'", ticker, col)
            return None

    ema_fast = _ema(df["close"], EMA_FAST)
    ema_slow = _ema(df["close"], EMA_SLOW)

    # 1) Fresh golden cross على آخر شمعة (rising edge — يطابق backtest V1)
    fresh_cross = (
        ema_fast.iloc[-1] > ema_slow.iloc[-1]
        and ema_fast.iloc[-2] <= ema_slow.iloc[-2]
    )
    if not fresh_cross:
        return None

    # 2) ADX ≥ 20
    adx_series = _adx(df)
    adx_val = float(adx_series.iloc[-1])
    if np.isnan(adx_val) or adx_val < ADX_MIN:
        if ticker:
            logger.debug("TREND[%s]: cross but ADX=%.1f < %.0f", ticker, adx_val, ADX_MIN)
        return None

    # 3) RSI > 50
    rsi_val = float(_rsi(df["close"]).iloc[-1])
    if np.isnan(rsi_val) or rsi_val <= RSI_MIN:
        if ticker:
            logger.debug("TREND[%s]: cross but RSI=%.1f <= %.0f", ticker, rsi_val, RSI_MIN)
        return None

    # 4) Liquidity floor
    adt_val = adt if adt is not None else _adt(df)
    if adt_val < MIN_ADT_EGP:
        if ticker:
            logger.debug("TREND[%s]: cross but ADT=%.0f < %d", ticker, adt_val, MIN_ADT_EGP)
        return None

    # 5) Optional bear floor
    if require_breadth and breadth_pct <= BREADTH_MIN:
        if ticker:
            logger.debug("TREND[%s]: cross but breadth=%.1f <= %.0f", ticker, breadth_pct, BREADTH_MIN)
        return None

    grade = _grade_from_adx(adx_val)
    if _GRADE_RANK.get(grade, 0) < _GRADE_RANK.get(min_grade, 1):
        return None

    entry   = float(df["close"].iloc[-1])
    atr_raw = float(_atr(df).iloc[-1])
    atr_val = atr_raw if not np.isnan(atr_raw) and atr_raw > 0 else entry * 0.02

    fast_p, bal_p = PROFILES["FAST"], PROFILES["BALANCED"]

    # trend_strength: رقم عرض/ثقة (مش بوابة) — يرتفع مع ADX والزخم
    trend_strength = float(min(100.0, round(adx_val * 1.6 + max(0.0, rsi_val - 50.0) * 0.8 + 20.0, 1)))

    reasons = [
        f"🚀 Fresh EMA{EMA_FAST}/{EMA_SLOW} golden cross — بداية اتجاه",
        f"✅ ADX={adx_val:.0f} — تأكيد قوة الاتجاه",
        f"✅ RSI={rsi_val:.0f} — زخم إيجابي",
    ]
    if adt_val >= 10_000_000:
        reasons.append(f"💧 سيولة عالية ({adt_val/1e6:.0f}M ج/يوم)")

    result = TrendResult(
        ticker            = ticker,
        signal_family     = "TREND",
        grade             = grade,
        trend_strength    = trend_strength,
        adx               = round(adx_val, 2),
        rsi               = round(rsi_val, 2),
        ema_fast          = round(float(ema_fast.iloc[-1]), 4),
        ema_slow          = round(float(ema_slow.iloc[-1]), 4),
        market_breadth    = breadth_pct,
        adt               = adt_val,
        entry_price       = round(entry, 4),
        atr               = round(atr_val, 4),
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
            "TREND[%s]: SIGNAL %s strength=%.0f adx=%.0f rsi=%.0f entry=%.4f",
            ticker, result.opp_type, trend_strength, adx_val, rsi_val, entry,
        )
    return result
