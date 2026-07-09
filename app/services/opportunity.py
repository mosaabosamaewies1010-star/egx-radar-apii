"""
Opportunity Engine — generates Entry/TP1/TP2/SL levels.
Based on ATR multiples from the Quant Bible.
"""
from dataclasses import dataclass
from typing import Optional

from app.services.indicators import Indicators
from app.services.radar_score import ScoreBreakdown

# Minimum Radar Score to generate an opportunity
MIN_SCORE_FOR_OPPORTUNITY = 60
MIN_RR_RATIO = 1.5


@dataclass
class OpportunityResult:
    opp_type:       str     # Breakout|Momentum|Swing|Sharia
    entry_price:    float
    tp1_price:      float
    tp2_price:      float
    sl_price:       float
    rr_ratio:       float
    max_hold_days:  int
    signal_quality: str     # HIGH|MEDIUM|LOW
    reason_ar:      str
    reason_en:      str


def compute_opportunity(
    ind: Indicators,
    bd: ScoreBreakdown,
    is_sharia: bool = False,
    regime: str = "SIDEWAYS",
) -> Optional[OpportunityResult]:
    """
    Returns None if no valid opportunity (score too low or R/R < 1.5).
    """
    if bd.final_score < MIN_SCORE_FOR_OPPORTUNITY:
        return None

    price = ind.price
    atr   = ind.atr

    opp_type = _classify_opportunity(ind, bd, is_sharia)
    multipliers = _get_multipliers(opp_type, regime)

    entry = price                                              # buy at current price (market order zone)
    sl    = round(entry - atr * multipliers["sl"], 4)
    tp1   = round(entry + atr * multipliers["tp1"], 4)
    tp2   = round(entry + atr * multipliers["tp2"], 4)

    risk   = entry - sl
    reward = tp1 - entry

    if risk <= 0:
        return None

    rr = round(reward / risk, 2)
    if rr < MIN_RR_RATIO:
        return None

    signal_quality = _signal_quality(bd, ind)
    reason_ar, reason_en = _opportunity_reason(opp_type, ind, bd)

    return OpportunityResult(
        opp_type=opp_type,
        entry_price=round(entry, 4),
        tp1_price=tp1,
        tp2_price=tp2,
        sl_price=sl,
        rr_ratio=rr,
        max_hold_days=_max_hold_days(opp_type),
        signal_quality=signal_quality,
        reason_ar=reason_ar,
        reason_en=reason_en,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _classify_opportunity(ind: Indicators, bd: ScoreBreakdown, is_sharia: bool) -> str:
    if is_sharia and bd.final_score >= 70:
        return "Sharia"
    if ind.adx >= 30 and ind.rvol > 1.5 and ind.macd_hist > 0:
        return "Breakout"
    if 55 <= ind.rsi <= 70 and ind.rvol >= 1.2:
        return "Momentum"
    return "Swing"


def _get_multipliers(opp_type: str, regime: str) -> dict:
    """ATR multipliers for SL, TP1, TP2."""
    base = {
        "Breakout":  {"sl": 1.5, "tp1": 2.5, "tp2": 4.0},
        "Momentum":  {"sl": 1.2, "tp1": 2.0, "tp2": 3.5},
        "Swing":     {"sl": 1.0, "tp1": 1.8, "tp2": 3.0},
        "Sharia":    {"sl": 1.2, "tp1": 2.0, "tp2": 3.5},
    }.get(opp_type, {"sl": 1.2, "tp1": 2.0, "tp2": 3.5})

    # Tighten TP in bear/volatile regime
    if regime in ("BEAR", "VOLATILE"):
        base["tp1"] = round(base["tp1"] * 0.85, 2)
        base["tp2"] = round(base["tp2"] * 0.85, 2)

    return base


def _max_hold_days(opp_type: str) -> int:
    return {"Breakout": 10, "Momentum": 12, "Swing": 15, "Sharia": 12}.get(opp_type, 12)


def _signal_quality(bd: ScoreBreakdown, ind: Indicators) -> str:
    if bd.final_score >= 80 and ind.rvol >= 1.5 and ind.data_quality == "HIGH":
        return "HIGH"
    if bd.final_score >= 65:
        return "MEDIUM"
    return "LOW"


def _opportunity_reason(opp_type: str, ind: Indicators, bd: ScoreBreakdown) -> tuple[str, str]:
    reasons = {
        "Breakout": (
            f"اختراق قوي — ADX {ind.adx:.0f} مع حجم {ind.rvol:.1f}x المعتاد وتأكيد MACD",
            f"Strong breakout — ADX {ind.adx:.0f} with {ind.rvol:.1f}x volume and MACD confirmation",
        ),
        "Momentum": (
            f"زخم إيجابي — RSI في المنطقة المثالية ({ind.rsi:.0f}) مع حجم مرتفع",
            f"Positive momentum — RSI in sweet spot ({ind.rsi:.0f}) with elevated volume",
        ),
        "Swing": (
            f"فرصة تأرجح — نقاط دعم/مقاومة واضحة بنسبة مخاطرة/عائد {bd.final_score:.0f}",
            f"Swing opportunity — clear support/resistance with score {bd.final_score:.0f}",
        ),
        "Sharia": (
            f"فرصة متوافقة مع الشريعة — نتيجة رادار {bd.final_score:.0f} مع زخم إيجابي",
            f"Sharia-compliant opportunity — Radar Score {bd.final_score:.0f} with positive momentum",
        ),
    }
    return reasons.get(opp_type, ("فرصة محتملة", "Potential opportunity"))
