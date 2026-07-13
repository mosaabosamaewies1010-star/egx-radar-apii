from flask import Blueprint, jsonify, request
from sqlalchemy import func, case
from app import db
from app.models import Opportunity, Stock, StrategyVersion

performance_bp = Blueprint("performance", __name__)


def _win_rate(wins: int, total: int) -> float | None:
    return round(wins / total * 100, 1) if total else None


def _profit_factor(gross_wins: float, gross_losses: float) -> float | None:
    if gross_losses == 0:
        return None
    return round(abs(gross_wins / gross_losses), 3)


def _expectancy(avg_win: float | None, avg_loss: float | None, win_rate_pct: float | None) -> float | None:
    if any(v is None for v in (avg_win, avg_loss, win_rate_pct)):
        return None
    wr = win_rate_pct / 100
    return round(wr * avg_win + (1 - wr) * avg_loss, 2)


def _slice_stats(rows):
    """Compute performance stats from a list of Opportunity ORM objects."""
    total = len(rows)
    if total == 0:
        return None

    closed = [r for r in rows if r.pnl_pct is not None]
    wins   = [r for r in closed if r.pnl_pct > 0]
    losses = [r for r in closed if r.pnl_pct <= 0]

    avg_win  = round(sum(r.pnl_pct for r in wins)   / len(wins),   2) if wins   else None
    avg_loss = round(sum(r.pnl_pct for r in losses) / len(losses), 2) if losses else None
    wr       = _win_rate(len(wins), len(closed))

    gross_wins   = sum(r.pnl_pct for r in wins)
    gross_losses = sum(r.pnl_pct for r in losses)   # negative numbers

    avg_hold = round(sum(r.hold_days for r in closed if r.hold_days) / len(closed), 1) if closed else None

    return {
        "total":          total,
        "closed":         len(closed),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate":       wr,
        "avg_win_pct":    avg_win,
        "avg_loss_pct":   avg_loss,
        "profit_factor":  _profit_factor(gross_wins, gross_losses),
        "expectancy":     _expectancy(avg_win, avg_loss, wr),
        "avg_hold_days":  avg_hold,
        "tp1_rate":       round(len([r for r in closed if r.exit_reason == "TP1"]) / len(closed) * 100, 1) if closed else None,
        "sl_rate":        round(len([r for r in closed if r.exit_reason in ("SL", "SL_same_bar")]) / len(closed) * 100, 1) if closed else None,
    }


@performance_bp.get("/api/performance")
def performance():
    rows = (
        Opportunity.query
        .filter(Opportunity.outcome.in_(["WIN", "LOSS", "EXPIRED"]))
        .all()
    )

    if not rows:
        return jsonify({"total": 0, "message": "لا توجد بيانات أداء بعد"}), 200

    # ── Overall ──────────────────────────────────────────────────────────────
    overall = _slice_stats(rows)

    # ── By year ───────────────────────────────────────────────────────────────
    by_year: dict[int, list] = {}
    for r in rows:
        y = r.run_date.year
        by_year.setdefault(y, []).append(r)
    years = [
        {"year": y, **_slice_stats(rs)}
        for y, rs in sorted(by_year.items())
    ]

    # ── By sector (from feature_snapshot) ────────────────────────────────────
    by_sector: dict[str, list] = {}
    for r in rows:
        sector = (r.feature_snapshot or {}).get("sector") or r.stock.sector or "غير محدد"
        by_sector.setdefault(sector, []).append(r)
    sectors = sorted(
        [{"sector": s, **_slice_stats(rs)} for s, rs in by_sector.items()],
        key=lambda x: -(x.get("profit_factor") or 0),
    )

    # ── By strategy version ───────────────────────────────────────────────────
    by_version: dict[str, list] = {}
    for r in rows:
        v = r.strategy_version.version if r.strategy_version else "unknown"
        by_version.setdefault(v, []).append(r)
    versions = [
        {"version": v, **_slice_stats(rs)}
        for v, rs in by_version.items()
    ]

    # ── Top performing stocks ─────────────────────────────────────────────────
    by_symbol: dict[str, list] = {}
    for r in rows:
        by_symbol.setdefault(r.stock.symbol, []).append(r)
    top_stocks = sorted(
        [
            {
                "symbol":  sym,
                "name_ar": rs[0].stock.name_ar,
                "sector":  (rs[0].feature_snapshot or {}).get("sector") or rs[0].stock.sector,
                **(_slice_stats(rs) or {}),
            }
            for sym, rs in by_symbol.items()
            if len(rs) >= 3   # at least 3 trades for meaningful stats
        ],
        key=lambda x: -(x.get("profit_factor") or 0),
    )[:10]

    return jsonify({
        "overall":    overall,
        "by_year":    years,
        "by_sector":  sectors,
        "by_version": versions,
        "top_stocks": top_stocks,
    })


@performance_bp.get("/api/performance/trades")
def trade_history():
    """Paginated list of closed trades for the trade-history view."""
    limit   = min(int(request.args.get("limit",  50)), 200)
    offset  = int(request.args.get("offset", 0))
    outcome = request.args.get("outcome", "").upper()   # WIN | LOSS | EXPIRED | (all)
    symbol  = request.args.get("symbol",  "").upper()

    query = (
        Opportunity.query
        .join(Stock)
        .filter(Opportunity.outcome.in_(["WIN", "LOSS", "EXPIRED"]))
        .order_by(Opportunity.closed_at.desc(), Opportunity.id.desc())
    )

    if outcome in ("WIN", "LOSS", "EXPIRED"):
        query = query.filter(Opportunity.outcome == outcome)
    if symbol:
        query = query.filter(Stock.symbol == symbol)

    total = query.count()
    trades = query.offset(offset).limit(limit).all()

    def _trade(o: Opportunity) -> dict:
        snap = o.feature_snapshot or {}
        return {
            "id":             o.id,
            "symbol":         o.stock.symbol,
            "name_ar":        o.stock.name_ar,
            "sector":         o.stock.sector,
            "is_sharia":      o.stock.is_sharia,
            "opp_type":       o.opp_type,
            "radar_score":    o.radar_score,
            "signal_quality": o.signal_quality,
            "run_date":       o.run_date.isoformat() if o.run_date else None,
            "closed_at":      o.closed_at.isoformat() if o.closed_at else None,
            "hold_days":      o.hold_days,
            "outcome":        o.outcome,
            "exit_reason":    o.exit_reason,
            "pnl_pct":        o.pnl_pct,
            "entry_price":    o.entry_price,
            "exit_price":     o.exit_price,
            "tp1_price":      o.tp1_price,
            "tp2_price":      o.tp2_price,
            "sl_price":       o.sl_price,
            "rr_ratio":       o.rr_ratio,
            "regime":         snap.get("regime"),
            "sra_grade":      snap.get("sra_grade"),
            "sra_score":      snap.get("sra_score"),
        }

    return jsonify({
        "total":  total,
        "limit":  limit,
        "offset": offset,
        "trades": [_trade(o) for o in trades],
    })
