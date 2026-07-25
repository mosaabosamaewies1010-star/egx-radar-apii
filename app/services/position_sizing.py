"""
Position Sizing Engine — answers "كم سهم أشتري؟"

Model: Volatility-Adjusted Fixed-Risk
  shares = floor((portfolio × final_risk_pct / 100) / (entry - sl))

final_risk_pct = base_risk × confidence_modifier × regime_modifier

base_risk per engine type (FROZEN with Core Engine v1.0):
  STAGE_STRONG:    2.0%
  STAGE_DEVELOPING: 1.5%
  TREND_A+:        1.5%
  TREND_A:         1.0%
  VOL_RADAR:       0.0%   ← never size a watch signal

confidence_modifier:
  80-100 → 1.00  (full size)
  60-79  → 0.75
  40-59  → 0.50
  <40    → 0.25  (quarter size — low conviction)

regime_modifier:
  BULL          → 1.00
  SIDEWAYS      → 0.75
  VOLATILE      → 0.50
  LOW_LIQUIDITY → 0.50
  BEAR          → 0.25

Hard constraints:
  max position = 25% of portfolio (concentration limit)
  min position = 1,000 EGP (otherwise round-lot math breaks)
"""
from __future__ import annotations
from dataclasses import dataclass
from math import floor

_BASE_RISK: dict[str, float] = {
    "STAGE_STRONG":    2.0,
    "STAGE_DEVELOPING": 1.5,
    "TREND_A+":        1.5,
    "TREND_A":         1.0,
    "VOL_RADAR":       0.0,
}

_CONF_MOD = [
    (80, 1.00),
    (60, 0.75),
    (40, 0.50),
    (0,  0.25),
]

_REGIME_MOD: dict[str, float] = {
    "BULL":          1.00,
    "SIDEWAYS":      0.75,
    "VOLATILE":      0.50,
    "LOW_LIQUIDITY": 0.50,
    "BEAR":          0.25,
}

MAX_POSITION_PCT = 25.0
MIN_POSITION_EGP = 1_000.0


@dataclass
class SizingResult:
    opp_type:       str
    confidence:     int
    regime:         str
    entry:          float
    sl:             float
    tp1:            float | None
    risk_per_share: float
    base_risk_pct:  float
    conf_modifier:  float
    regime_modifier: float
    final_risk_pct: float
    risk_egp:       float
    shares:         int
    position_egp:   float
    position_pct:   float
    max_loss_egp:   float
    potential_gain_egp: float | None
    rr:             float | None
    warning:        str | None

    def to_dict(self) -> dict:
        return {
            "opp_type":          self.opp_type,
            "confidence":        self.confidence,
            "regime":            self.regime,
            "entry":             self.entry,
            "sl":                self.sl,
            "tp1":               self.tp1,
            "risk_per_share":    round(self.risk_per_share, 4),
            "base_risk_pct":     self.base_risk_pct,
            "conf_modifier":     self.conf_modifier,
            "regime_modifier":   self.regime_modifier,
            "final_risk_pct":    round(self.final_risk_pct, 3),
            "risk_egp":          round(self.risk_egp, 2),
            "shares":            self.shares,
            "position_egp":      round(self.position_egp, 2),
            "position_pct":      round(self.position_pct, 2),
            "max_loss_egp":      round(self.max_loss_egp, 2),
            "potential_gain_egp": round(self.potential_gain_egp, 2) if self.potential_gain_egp else None,
            "rr":                self.rr,
            "warning":           self.warning,
        }


def size_position(
    opp_type:     str,
    confidence:   int,
    regime:       str,
    entry:        float,
    sl:           float,
    tp1:          float | None,
    portfolio_egp: float,
) -> SizingResult | None:
    """
    Returns None for VOL_RADAR or when sl >= entry (invalid setup).
    Returns SizingResult with shares=0 when portfolio is too small.
    """
    base_risk = _BASE_RISK.get(opp_type, 0.0)
    if base_risk == 0.0:
        return None  # VOL_RADAR — no position, ever

    risk_per_share = entry - sl
    if risk_per_share <= 0:
        return None  # SL above or at entry — invalid

    # Confidence modifier
    conf_mod = 0.25
    for threshold, mod in _CONF_MOD:
        if confidence >= threshold:
            conf_mod = mod
            break

    regime_mod    = _REGIME_MOD.get(regime, 0.75)
    final_risk_pct = base_risk * conf_mod * regime_mod
    risk_egp      = portfolio_egp * final_risk_pct / 100.0
    shares        = floor(risk_egp / risk_per_share)

    warning: str | None = None

    if shares < 1:
        return SizingResult(
            opp_type=opp_type, confidence=confidence, regime=regime,
            entry=entry, sl=sl, tp1=tp1,
            risk_per_share=risk_per_share,
            base_risk_pct=base_risk, conf_modifier=conf_mod,
            regime_modifier=regime_mod, final_risk_pct=final_risk_pct,
            risk_egp=risk_egp, shares=0,
            position_egp=0.0, position_pct=0.0,
            max_loss_egp=0.0, potential_gain_egp=None, rr=None,
            warning="المحفظة صغيرة جداً أو سعر السهم مرتفع",
        )

    position_egp = shares * entry
    position_pct = position_egp / portfolio_egp * 100.0

    # Cap at 25% concentration limit
    if position_pct > MAX_POSITION_PCT:
        shares       = floor(portfolio_egp * MAX_POSITION_PCT / 100.0 / entry)
        position_egp = shares * entry
        position_pct = position_egp / portfolio_egp * 100.0
        warning      = f"مقيّد عند {MAX_POSITION_PCT:.0f}٪ — لا تُركّز أكثر من ربع المحفظة في سهم واحد"

    if position_egp < MIN_POSITION_EGP:
        warning = f"الحجم أقل من الحد الأدنى ({MIN_POSITION_EGP:,.0f} ج.م)"

    max_loss_egp       = shares * risk_per_share
    potential_gain_egp = shares * (tp1 - entry) if tp1 and tp1 > entry else None
    rr = round((tp1 - entry) / risk_per_share, 2) if tp1 and tp1 > entry else None

    return SizingResult(
        opp_type=opp_type, confidence=confidence, regime=regime,
        entry=entry, sl=sl, tp1=tp1,
        risk_per_share=risk_per_share,
        base_risk_pct=base_risk, conf_modifier=conf_mod,
        regime_modifier=regime_mod, final_risk_pct=final_risk_pct,
        risk_egp=risk_egp, shares=shares,
        position_egp=position_egp, position_pct=position_pct,
        max_loss_egp=max_loss_egp,
        potential_gain_egp=potential_gain_egp,
        rr=rr, warning=warning,
    )
