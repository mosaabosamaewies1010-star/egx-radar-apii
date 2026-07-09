"""
Market Regime Engine.
Classifies the EGX market into BULL / SIDEWAYS / BEAR / VOLATILE / LOW_LIQUIDITY.
Uses EGX30 index data + market breadth snapshot.
"""
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from app.services.indicators import Indicators, compute_indicators
from app.utils.data_fetcher import fetch_ohlcv, assess_data_quality

EGX30_TICKER = "^EGX30"   # yfinance symbol for EGX30 index


@dataclass
class RegimeResult:
    regime:     str     # BULL|SIDEWAYS|BEAR|VOLATILE|LOW_LIQUIDITY
    confidence: float   # 0-100

    ma_score:        float
    breadth_score:   float
    adx_score:       float
    volatility_score: float
    volume_score:    float

    # EGX30 snapshot
    egx30_close: float
    egx30_ma20:  float
    egx30_ma50:  float
    egx30_ma200: float

    # Breadth (passed in externally from breadth_snapshot)
    advancing: int
    declining: int
    unchanged: int

    reason_ar: str
    reason_en: str


def compute_market_regime(
    breadth: Optional[dict] = None,  # {"advancing": int, "declining": int, "unchanged": int}
) -> Optional[RegimeResult]:
    """
    Compute market regime from EGX30 index data + optional breadth data.
    breadth can be None — we fall back to estimated neutral breadth.
    """
    df = fetch_ohlcv(EGX30_TICKER, period="1y")
    if df is None or len(df) < 30:
        return None

    quality = assess_data_quality(df, EGX30_TICKER)
    ind = compute_indicators(df, quality)
    if ind is None:
        return None

    # ── Component Scores ──────────────────────────────────────────────
    ma_score         = _ma_score(ind)
    breadth_score    = _breadth_score(breadth)
    adx_score        = _adx_score(ind)
    volatility_score = _volatility_score(ind)
    volume_score_val = _volume_score(ind)

    total = ma_score + breadth_score + adx_score + volatility_score + volume_score_val

    advancing = (breadth or {}).get("advancing", 0)
    declining  = (breadth or {}).get("declining", 0)
    unchanged  = (breadth or {}).get("unchanged", 0)

    regime, confidence = _classify_regime(
        total=total,
        ind=ind,
        breadth=breadth,
        adx_score=adx_score,
        volatility_score=volatility_score,
    )

    reason_ar, reason_en = _generate_reason(regime, ind, breadth)

    return RegimeResult(
        regime=regime,
        confidence=round(confidence, 1),
        ma_score=round(ma_score, 2),
        breadth_score=round(breadth_score, 2),
        adx_score=round(adx_score, 2),
        volatility_score=round(volatility_score, 2),
        volume_score=round(volume_score_val, 2),
        egx30_close=ind.price,
        egx30_ma20=ind.ma20,
        egx30_ma50=ind.ma50,
        egx30_ma200=ind.ma200,
        advancing=advancing,
        declining=declining,
        unchanged=unchanged,
        reason_ar=reason_ar,
        reason_en=reason_en,
    )


# ── Component Scorers ─────────────────────────────────────────────────────────

def _ma_score(ind: Indicators) -> float:
    """30 pts — EGX30 vs its moving averages."""
    score = 0.0
    if ind.price > ind.ma20:   score += 10
    if ind.price > ind.ma50:   score += 10
    if ind.price > ind.ma200:  score += 10
    return score


def _breadth_score(breadth: Optional[dict]) -> float:
    """25 pts — market breadth (advancing vs declining ratio)."""
    if not breadth:
        return 12.5  # neutral when no data

    adv = breadth.get("advancing", 0)
    dec = breadth.get("declining", 0)
    total = adv + dec
    if total == 0:
        return 12.5

    ratio = adv / total
    if ratio >= 0.70:   return 25
    if ratio >= 0.55:   return 19
    if ratio >= 0.45:   return 12.5
    if ratio >= 0.30:   return 6
    return 0


def _adx_score(ind: Indicators) -> float:
    """20 pts — trend strength."""
    if ind.adx >= 35:   return 20
    if ind.adx >= 25:   return 14
    if ind.adx >= 15:   return 7
    return 2


def _volatility_score(ind: Indicators) -> float:
    """
    15 pts — low ATR% is good (stable market).
    ATR% < 1% → 15, 1–2% → 10, 2–4% → 5, > 4% → 0.
    """
    atr = ind.atr_pct
    if atr < 1.0:   return 15
    if atr < 2.0:   return 10
    if atr < 4.0:   return 5
    return 0


def _volume_score(ind: Indicators) -> float:
    """10 pts — RVOL above average = healthy participation."""
    if ind.rvol >= 1.5:  return 10
    if ind.rvol >= 1.0:  return 7
    if ind.rvol >= 0.7:  return 4
    return 0


# ── Classification ────────────────────────────────────────────────────────────

def _classify_regime(
    total: float,
    ind: Indicators,
    breadth: Optional[dict],
    adx_score: float,
    volatility_score: float,
) -> tuple[str, float]:
    """
    Classify regime from total score (0-100) + override conditions.
    Returns (regime, confidence 0-100).
    """
    # Override: VOLATILE takes priority when ATR is extreme
    if ind.atr_pct >= 4.0:
        conf = 60 + min(ind.atr_pct * 5, 35)
        return "VOLATILE", min(conf, 95)

    # Override: LOW_LIQUIDITY when RVOL is very low
    if ind.rvol < 0.4:
        return "LOW_LIQUIDITY", 70

    # Score-based classification (max score = 100)
    pct = total / 100 * 100

    if pct >= 65:
        return "BULL", min(50 + pct * 0.7, 95)
    if pct >= 40:
        return "SIDEWAYS", 60 + (pct - 40) * 0.5
    if pct >= 20:
        return "BEAR", 60 + (40 - pct) * 0.75
    return "BEAR", 90


# ── Reason Generator ─────────────────────────────────────────────────────────

def _generate_reason(
    regime: str,
    ind: Indicators,
    breadth: Optional[dict],
) -> tuple[str, str]:

    adv = (breadth or {}).get("advancing", 0)
    dec = (breadth or {}).get("declining", 0)
    breadth_note_ar = f"{adv} سهم صاعد مقابل {dec} هابط" if adv or dec else "بيانات الاتساع غير متاحة"
    breadth_note_en = f"{adv} advancing vs {dec} declining" if adv or dec else "breadth data unavailable"

    reasons = {
        "BULL": (
            f"السوق في مرحلة صعود — مؤشر EGX30 فوق متوسطاته الرئيسية، {breadth_note_ar}، والزخم إيجابي.",
            f"Bullish market — EGX30 is above key MAs, {breadth_note_en}, positive momentum.",
        ),
        "SIDEWAYS": (
            f"السوق في مرحلة تذبذب — EGX30 يتحرك في نطاق ضيق بدون اتجاه واضح. {breadth_note_ar}.",
            f"Sideways market — EGX30 range-bound without clear direction. {breadth_note_en}.",
        ),
        "BEAR": (
            f"السوق في مرحلة هبوط — EGX30 تحت متوسطاته الرئيسية، {breadth_note_ar}، والضغط البيعي سائد.",
            f"Bearish market — EGX30 below key MAs, {breadth_note_en}, selling pressure dominant.",
        ),
        "VOLATILE": (
            f"السوق متقلب — ATR مرتفع ({ind.atr_pct:.1f}٪) يشير إلى تذبذب حاد. المخاطرة مرتفعة الآن.",
            f"Volatile market — high ATR ({ind.atr_pct:.1f}%) signals sharp swings. Risk is elevated.",
        ),
        "LOW_LIQUIDITY": (
            f"سيولة منخفضة — الحجم أقل بكثير من المعدل الطبيعي (RVOL {ind.rvol:.2f}). تجنب الصفقات الكبيرة.",
            f"Low liquidity — volume well below average (RVOL {ind.rvol:.2f}). Avoid large positions.",
        ),
    }

    return reasons.get(regime, ("غير محدد", "Unknown"))
