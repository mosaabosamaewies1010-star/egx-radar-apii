"""
Unified Confidence Score (0-100) across all 3 engine types.

Scale:
  80-100 → Very High  (strong signal + favorable regime)
  60-79  → High
  40-59  → Medium
  20-39  → Watch       (VOL_RADAR hard-capped here)
   0-19  → Low

VOL_RADAR is hard-capped at 60 — it is a watch/discovery signal,
never a buy recommendation. Stage and Trend can reach 100.

Regime bonus map:
  BULL           +10
  SIDEWAYS       +5
  VOLATILE       -5
  BEAR           -15
  LOW_LIQUIDITY   0
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.opportunity import Opportunity

_REGIME_PTS: dict[str, int] = {
    "BULL":          10,
    "SIDEWAYS":       5,
    "VOLATILE":      -5,
    "BEAR":         -15,
    "LOW_LIQUIDITY":  0,
}


def compute_confidence(opp: "Opportunity") -> int:
    """Return unified confidence score 0-100 for any engine type."""
    snap = opp.feature_snapshot
    if not isinstance(snap, dict):
        snap = {}
    regime = snap.get("regime", "SIDEWAYS")

    if opp.opp_type in ("STAGE_STRONG", "STAGE_DEVELOPING"):
        return _stage_confidence(opp, snap, regime)
    if opp.opp_type in ("TREND_A+", "TREND_A"):
        return _trend_confidence(opp, snap, regime)
    if opp.opp_type == "VOL_RADAR":
        return _vol_confidence(snap, regime)

    # Legacy types — clamp radar_score to 0-100
    return max(0, min(100, int(opp.radar_score or 0)))


# ── per-engine helpers ────────────────────────────────────────────────────────

def _stage_confidence(opp: "Opportunity", snap: dict, regime: str) -> int:
    """
    Stage Breakout confidence.
    Components:
      base      0-60  from stage_score (already 0-100, capped at 60)
      freshness 0-20  VOL spike age: 0 bars → 20 pts, 60 bars → 0 pts
      strength  4-10  STRONG=10, DEVELOPING=4
      regime    -15..+10
    """
    age_bars   = int(snap.get("vol_age_bars", 60))
    base       = min(60, int(snap.get("stage_score", opp.radar_score or 50)))
    freshness  = int(max(0.0, 1.0 - age_bars / 60.0) * 20)
    strength   = 10 if opp.opp_type == "STAGE_STRONG" else 4
    regime_pts = _REGIME_PTS.get(regime, 0)
    return max(0, min(100, base + freshness + strength + regime_pts))


def _trend_confidence(opp: "Opportunity", snap: dict, regime: str) -> int:
    """
    Trend Initiation confidence.
    Components:
      grade_base 40-50  A+=50, A=40
      adx_bonus  0-15   ADX 20→45 linear
      rsi_bonus  0-10   sweet spot RSI 50-65 = 10, borderline = 5, else 0
      regime     -15..+10
    """
    grade_base = 50 if opp.opp_type == "TREND_A+" else 40
    adx        = float(snap.get("adx", 20))
    rsi        = float(snap.get("rsi", 55))
    adx_bonus  = int(min(15, max(0.0, (adx - 20) / 25.0 * 15)))
    if 50 <= rsi <= 65:
        rsi_bonus = 10
    elif 45 <= rsi < 50 or 65 < rsi <= 70:
        rsi_bonus = 5
    else:
        rsi_bonus = 0
    regime_pts = _REGIME_PTS.get(regime, 0)
    return max(0, min(100, grade_base + adx_bonus + rsi_bonus + regime_pts))


def _vol_confidence(snap: dict, regime: str) -> int:
    """
    Volume Radar confidence — hard-capped at 60 (watch signal only).
    Components:
      base       20     minimum watch baseline
      rvol_pts   0-25   RVOL 1.8→4.0 linear (1.8 = threshold, 4.0 = max)
      freshness  0-20   same as stage
      regime     0..+10 (negative regime → 0, not penalised for watch signals)
    """
    rvol      = float(snap.get("vol_rvol", 1.8))
    age_bars  = int(snap.get("vol_age_bars", 60))
    rvol_pts  = int(min(25, max(0.0, (rvol - 1.8) / 2.2 * 25)))
    freshness = int(max(0.0, 1.0 - age_bars / 60.0) * 20)
    # No negative regime penalty for watch signals — market stays bearish,
    # VOL patterns still worth watching for future breakouts.
    regime_pts = max(0, _REGIME_PTS.get(regime, 0))
    total = 20 + rvol_pts + freshness + regime_pts
    return max(0, min(60, total))  # hard cap
