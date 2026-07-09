"""
knowledge_base.py — query historical SRA outcomes from the Opportunity table.

Every closed SRA opportunity feeds this automatically.
No separate table needed — the Opportunity model IS the knowledge base.
"""
from __future__ import annotations
from statistics import median as _median
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ── Grade hierarchy ───────────────────────────────────────────────────────────
# When looking for "similar setups", A+ signal compares only to A+.
# A signal compares to A+ and A (both are high-quality setups).
# B signal compares to all SRA grades.
_GRADE_POOL = {
    "A+": ["SRA_A+"],
    "A":  ["SRA_A+", "SRA_A"],
    "B":  ["SRA_A+", "SRA_A", "SRA_B"],
}

# Confidence thresholds
_CONF_HIGH   = 50
_CONF_MEDIUM = 20
_CONF_LOW    = 5


def query_similar_setups(
    db,
    grade: str,
    regime: str,
    sector_positive: bool | None = None,
    min_closed: int = _CONF_LOW,
) -> dict:
    """
    Query closed SRA opportunities matching grade + regime from DB.

    Returns a dict ready to be merged into feature_snapshot:
        similar_cases, historical_win_rate, avg_return, median_return,
        best_case, worst_case, confidence
    """
    from app.models.opportunity import Opportunity

    allowed_types = _GRADE_POOL.get(grade, [f"SRA_{grade}"])

    # Base filter: closed SRA opps of matching grade pool with pnl recorded
    rows = (
        db.session.query(Opportunity)
        .filter(
            Opportunity.opp_type.in_(allowed_types),
            Opportunity.outcome.in_(["WIN", "LOSS", "EXPIRED"]),
            Opportunity.pnl_pct.isnot(None),
        )
        .all()
    )

    # Optional regime filter — only if we have enough rows after filtering
    regime_rows = [
        r for r in rows
        if (r.feature_snapshot or {}).get("regime") == regime
    ]
    if len(regime_rows) >= min_closed:
        rows = regime_rows

    empty = {
        "similar_cases":       len(rows),
        "historical_win_rate": 0.0,
        "avg_return":          0.0,
        "median_return":       0.0,
        "best_case":           0.0,
        "worst_case":          0.0,
        "confidence":          "none",
    }

    if len(rows) < min_closed:
        return empty

    pnls   = [r.pnl_pct for r in rows]
    wins   = [r for r in rows if r.outcome == "WIN"]
    losses = [r for r in rows if r.outcome == "LOSS"]

    win_rate       = round(len(wins) / len(rows) * 100, 1)
    avg_return     = round(sum(pnls) / len(pnls), 2)
    median_return  = round(_median(pnls), 2)
    best_case      = round(max(pnls), 2)
    worst_case     = round(min(pnls), 2)
    avg_win        = round(sum(r.pnl_pct for r in wins)   / len(wins),   2) if wins   else 0.0
    avg_loss       = round(sum(r.pnl_pct for r in losses) / len(losses), 2) if losses else 0.0

    n = len(rows)
    if n >= _CONF_HIGH:
        confidence = "high"
    elif n >= _CONF_MEDIUM:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "similar_cases":       n,
        "historical_win_rate": win_rate,
        "avg_return":          avg_return,
        "median_return":       median_return,
        "best_case":           best_case,
        "worst_case":          worst_case,
        "avg_win":             avg_win,
        "avg_loss":            avg_loss,
        "confidence":          confidence,
    }
