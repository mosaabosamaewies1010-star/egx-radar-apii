"""
Radar Score Engine — Quant Bible formula.
6 weighted components + Risk Penalty + Regime Multiplier → 0-100.
"""
from dataclasses import dataclass
from typing import Optional

from app.services.indicators import Indicators

# ── Weight constants (must sum to 95 before risk/regime) ─────────────────────
W_TREND       = 20
W_MOMENTUM    = 18
W_LIQUIDITY   = 16
W_VOLUME      = 14
W_SECTOR      = 12
W_FUNDAMENTAL = 15

MAX_RISK_PENALTY = 15

REGIME_MULTIPLIERS = {
    "BULL":          1.00,
    "SIDEWAYS":      0.90,
    "BEAR":          0.75,
    "VOLATILE":      0.85,
    "LOW_LIQUIDITY": 0.80,
}


@dataclass
class ScoreBreakdown:
    trend_score:       float
    momentum_score:    float
    liquidity_score:   float
    volume_score:      float
    sector_score:      float
    fundamental_score: float
    risk_penalty:      float
    regime_multiplier: float
    raw_score:         float
    final_score:       float


def compute_radar_score(
    ind: Indicators,
    adt: float,                         # Average Daily Turnover in EGP
    regime: str = "SIDEWAYS",
    sector_score: float = 6.0,          # 0–12 pts, computed externally
    fundamental_score: float = 7.5,     # 0–15 pts, computed externally
) -> ScoreBreakdown:
    """
    Compute Radar Score from indicators + market context.
    Returns full breakdown for explain engine and DB storage.
    """

    trend       = _trend_score(ind)
    momentum    = _momentum_score(ind)
    liquidity   = _liquidity_score(adt)
    volume      = _volume_score(ind)
    sector      = min(max(sector_score, 0), W_SECTOR)
    fundamental = min(max(fundamental_score, 0), W_FUNDAMENTAL)

    raw = trend + momentum + liquidity + volume + sector + fundamental
    raw = min(raw, 95)  # theoretical max before penalty

    risk_pen   = _risk_penalty(ind)
    multiplier = REGIME_MULTIPLIERS.get(regime, 0.90)

    final = (raw - risk_pen) * multiplier
    final = max(0.0, min(100.0, round(final, 1)))

    return ScoreBreakdown(
        trend_score=round(trend, 2),
        momentum_score=round(momentum, 2),
        liquidity_score=round(liquidity, 2),
        volume_score=round(volume, 2),
        sector_score=round(sector, 2),
        fundamental_score=round(fundamental, 2),
        risk_penalty=round(risk_pen, 2),
        regime_multiplier=multiplier,
        raw_score=round(raw, 2),
        final_score=final,
    )


# ── Component Scorers ─────────────────────────────────────────────────────────

def _trend_score(ind: Indicators) -> float:
    """
    0–20 pts.
    ADX ≥ 40 → 20, 25–39 → 14, 15–24 → 7, < 15 → 2.
    Bonus: +3 if price > MA20 > MA50 (uptrend alignment).
    Bonus: +2 if MACD histogram > 0 (momentum confirmation).
    """
    if ind.adx >= 40:
        base = 20
    elif ind.adx >= 25:
        base = 14
    elif ind.adx >= 15:
        base = 7
    else:
        base = 2

    bonus = 0
    if ind.price > ind.ma20 > ind.ma50:
        bonus += 3
    if ind.macd_hist > 0:
        bonus += 2

    # Cap at max weight
    return min(base + bonus, W_TREND)


def _momentum_score(ind: Indicators) -> float:
    """
    0–18 pts.
    RSI sweet spot 55–68 → 18, 45–54 or 69–75 → 12, 35–44 → 6, else → 0.
    Bonus: +3 if Williams%R > -30 (not overbought territory on short-term).
    Bonus: +2 if stoch_k > 50 and stoch_d > 50.
    Penalty: –3 if RSI > 75 (overbought risk).
    """
    rsi = ind.rsi
    if 55 <= rsi <= 68:
        base = 18
    elif (45 <= rsi < 55) or (69 <= rsi <= 75):
        base = 12
    elif 35 <= rsi < 45:
        base = 6
    else:
        base = 0

    bonus = 0
    if ind.williams_r > -30:
        bonus += 3
    if ind.stoch_k > 50 and ind.stoch_d > 50:
        bonus += 2

    penalty = 3 if rsi > 75 else 0

    return min(max(base + bonus - penalty, 0), W_MOMENTUM)


def _liquidity_score(adt: float) -> float:
    """
    0–16 pts based on Average Daily Turnover.
    < 3M EGP  → 0 (excluded from scoring)
    3–10M     → 4
    10–30M    → 8
    30–100M   → 12
    > 100M    → 16
    """
    if adt < 3_000_000:
        return 0
    if adt < 10_000_000:
        return 4
    if adt < 30_000_000:
        return 8
    if adt < 100_000_000:
        return 12
    return 16


def _volume_score(ind: Indicators) -> float:
    """
    0–14 pts based on RVOL (relative volume vs 20-day avg).
    RVOL > 2.5 → 14, 1.5–2.5 → 10, 1.0–1.5 → 7, 0.7–1.0 → 4, < 0.7 → 0.
    Bonus: +2 if OBV trend is UP.
    """
    rvol = ind.rvol
    if rvol > 2.5:
        base = 14
    elif rvol >= 1.5:
        base = 10
    elif rvol >= 1.0:
        base = 7
    elif rvol >= 0.7:
        base = 4
    else:
        base = 0

    bonus = 2 if ind.obv_trend == "UP" else 0
    return min(base + bonus, W_VOLUME)


def _risk_penalty(ind: Indicators) -> float:
    """
    0 to 15 pts subtracted.
    High ATR → volatility penalty.
    Price below MA200 → downtrend penalty.
    RSI extreme → overbought/oversold penalty.
    """
    penalty = 0.0

    # ATR%: 5%+ → max 6pts, 3–5% → 3pts, 1.5–3% → 1pt
    if ind.atr_pct >= 5.0:
        penalty += 6
    elif ind.atr_pct >= 3.0:
        penalty += 3
    elif ind.atr_pct >= 1.5:
        penalty += 1

    # Below MA200 (structural downtrend)
    if ind.price < ind.ma200:
        penalty += 4

    # Below MA50 (intermediate downtrend)
    if ind.price < ind.ma50:
        penalty += 2

    # RSI extremes
    if ind.rsi > 80 or ind.rsi < 25:
        penalty += 3

    return min(penalty, MAX_RISK_PENALTY)
