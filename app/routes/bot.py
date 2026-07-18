"""
Bot webhook — receives signals from egx_bot_v4.py.

The bot POSTs to /api/bot/signal with:
  Header:  X-Bot-Api-Key: <BOT_API_KEY>
  Body:    JSON signal payload (see _validate_signal)

This endpoint is the bridge between the live trading bot and the
Decision Moat: every inbound signal becomes an Opportunity row with
a frozen feature_snapshot capturing the full context at signal time.
"""
import os
import logging
from datetime import date, datetime, timezone

from flask import Blueprint, jsonify, request

from app import db
from app.models import Opportunity, Stock, StrategyVersion

logger = logging.getLogger(__name__)
bot_bp = Blueprint("bot", __name__)

_REQUIRED_SIGNAL_FIELDS = {"symbol", "entry_price", "tp1_price", "tp2_price", "sl_price"}


def _auth_check() -> bool:
    key = os.getenv("BOT_API_KEY", "")
    return bool(key) and request.headers.get("X-Bot-Api-Key") == key


def _get_or_create_stock(symbol: str, name_ar: str | None = None, sector: str | None = None) -> Stock:
    stock = Stock.query.filter_by(symbol=symbol).first()
    if stock is None:
        stock = Stock(
            symbol=symbol,
            name_ar=name_ar or symbol,
            name_en=symbol,
            sector=sector,
            is_active=True,
            is_sharia=False,
        )
        db.session.add(stock)
        db.session.flush()
    return stock


def _current_version() -> StrategyVersion | None:
    return (
        StrategyVersion.query
        .filter(StrategyVersion.effective_to.is_(None))
        .order_by(StrategyVersion.effective_from.desc())
        .first()
    )


# ── POST /api/bot/signal ───────────────────────────────────────────────────────

@bot_bp.post("/api/bot/signal")
def receive_signal():
    """
    Create an Opportunity from a bot signal.

    Required body fields: symbol, entry_price, tp1_price, tp2_price, sl_price
    Optional:  name_ar, sector, opp_type, radar_score, signal_quality,
               rr_ratio, max_hold_days, signal_date (YYYY-MM-DD),
               feature_snapshot (dict of all indicators at signal time)
    """
    if not _auth_check():
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}

    missing = _REQUIRED_SIGNAL_FIELDS - body.keys()
    if missing:
        return jsonify({"error": f"Missing fields: {sorted(missing)}"}), 400

    symbol = str(body["symbol"]).upper().strip()
    if not symbol:
        return jsonify({"error": "symbol cannot be empty"}), 400

    try:
        entry  = float(body["entry_price"])
        tp1    = float(body["tp1_price"])
        tp2    = float(body["tp2_price"])
        sl     = float(body["sl_price"])
    except (TypeError, ValueError):
        return jsonify({"error": "Price fields must be numeric"}), 400

    if not (sl < entry < tp1 <= tp2):
        return jsonify({"error": "Invalid levels: must satisfy sl < entry < tp1 <= tp2"}), 400

    sig_date_str = body.get("signal_date")
    try:
        sig_date = date.fromisoformat(sig_date_str) if sig_date_str else date.today()
    except ValueError:
        return jsonify({"error": "signal_date must be YYYY-MM-DD"}), 400

    # Idempotency — skip duplicate signal (same symbol + date + entry)
    existing = (
        Opportunity.query
        .join(Stock)
        .filter(Stock.symbol == symbol)
        .filter(Opportunity.run_date == sig_date)
        .filter(Opportunity.entry_price == entry)
        # dual-run: never treat a TREND_ record as a duplicate of a bot signal
        .filter(~Opportunity.opp_type.like("TREND_%"))
        .first()
    )

    if existing:
        return jsonify({"id": existing.id, "status": "duplicate"}), 200

    stock   = _get_or_create_stock(symbol, body.get("name_ar"), body.get("sector"))
    version = _current_version()

    rr = None
    if tp1 > entry and entry > sl:
        rr = round((tp1 - entry) / (entry - sl), 2)

    opp = Opportunity(
        stock_id            = stock.id,
        run_date            = sig_date,
        opp_type            = body.get("opp_type", "Bot"),
        entry_price         = entry,
        tp1_price           = tp1,
        tp2_price           = tp2,
        sl_price            = sl,
        rr_ratio            = body.get("rr_ratio", rr),
        max_hold_days       = int(body.get("max_hold_days", 20)),
        radar_score         = float(body.get("radar_score", 0.0)),
        signal_quality      = body.get("signal_quality", "MEDIUM"),
        outcome             = "PENDING",
        strategy_version_id = version.id if version else None,
        feature_snapshot    = body.get("feature_snapshot") or None,
    )

    db.session.add(opp)
    db.session.commit()

    logger.info("bot/signal: created opp %d for %s @ %.2f", opp.id, symbol, entry)
    return jsonify({"id": opp.id, "status": "created"}), 201


# ── POST /api/bot/outcome ──────────────────────────────────────────────────────

@bot_bp.post("/api/bot/outcome")
def receive_outcome():
    """
    Update outcome for an existing Opportunity.

    Body fields:
      opp_id      (int)    — Opportunity.id
      outcome     (str)    — WIN | LOSS | EXPIRED
      exit_reason (str)    — TP1 | TP2 | SL | SL_same_bar | timeout_20d | MANUAL
      exit_price  (float)  — actual exit price
      closed_date (str)    — YYYY-MM-DD (optional, defaults to today)
    """
    if not _auth_check():
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}

    opp_id = body.get("opp_id")
    if opp_id is None:
        return jsonify({"error": "opp_id required"}), 400

    opp = Opportunity.query.get(opp_id)
    if opp is None:
        return jsonify({"error": "Opportunity not found"}), 404

    outcome     = str(body.get("outcome", "")).upper()
    exit_reason = body.get("exit_reason")
    exit_price  = body.get("exit_price")

    if outcome not in ("WIN", "LOSS", "EXPIRED"):
        return jsonify({"error": "outcome must be WIN | LOSS | EXPIRED"}), 400

    closed_str = body.get("closed_date")
    try:
        closed_date = date.fromisoformat(closed_str) if closed_str else date.today()
    except ValueError:
        return jsonify({"error": "closed_date must be YYYY-MM-DD"}), 400

    pnl_pct   = None
    hold_days = None

    if exit_price is not None:
        try:
            exit_price = float(exit_price)
            pnl_pct    = round((exit_price - opp.entry_price) / opp.entry_price * 100, 2)
        except (TypeError, ValueError):
            pass

    if opp.run_date:
        delta     = closed_date - opp.run_date
        hold_days = max(0, delta.days)

    opp.outcome     = outcome
    opp.exit_reason = exit_reason
    opp.exit_price  = exit_price
    opp.pnl_pct     = pnl_pct
    opp.hold_days   = hold_days
    opp.closed_at   = closed_date

    db.session.commit()

    logger.info("bot/outcome: opp %d → %s (pnl=%.2f%%)", opp.id, outcome, pnl_pct or 0)
    return jsonify({"id": opp.id, "outcome": outcome, "pnl_pct": pnl_pct}), 200
