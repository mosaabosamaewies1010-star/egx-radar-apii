"""
Import historical backtest trades into the Flask API DB.

Usage:
    python scripts/import_backtest.py --csv PATH_TO_TRADES_CSV

Creates:
  - StrategyVersion "backtest_v1" (effective 2022-01-01 → 2026-01-01)
  - One Stock row per unique symbol (sector from CSV, sharia=False placeholder)
  - One Opportunity row per trade with full feature_snapshot (immutable)

Safe to re-run — skips existing symbols and existing opportunities
(matched by symbol + signal_date + entry_price).
"""

import sys, os, csv, argparse
from datetime import date, datetime

# ── bootstrap Flask app ──────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import create_app, db
from app.models import Stock, Opportunity, StrategyVersion

# ── outcome mapping ───────────────────────────────────────────────────────────
def map_outcome(exit_reason: str) -> str:
    if exit_reason in ("TP1", "TP2"):
        return "WIN"
    if exit_reason in ("SL", "SL_same_bar"):
        return "LOSS"
    return "EXPIRED"   # timeout_20d, end_of_test


def run(csv_path: str, dry_run: bool = False):
    app = create_app()
    with app.app_context():
        db.create_all()

        # ── 1. StrategyVersion ────────────────────────────────────────────────
        sv = StrategyVersion.query.filter_by(version="backtest_v1").first()
        if not sv:
            sv = StrategyVersion(
                version        = "backtest_v1",
                description    = "Backtest results 2022–2026 (egx_backtest.py). "
                                 "Features: EMA, RSI, BB, OBV, ADX, VolSurge, BBSqueeze, MFI, RelStrength.",
                effective_from = date(2022, 1, 1),
                effective_to   = date(2026, 1, 1),
            )
            db.session.add(sv)
            db.session.flush()
            print(f"Created StrategyVersion: {sv.version}")
        else:
            print(f"StrategyVersion already exists: {sv.version}")

        # ── 2. Read CSV ───────────────────────────────────────────────────────
        with open(csv_path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        print(f"CSV rows: {len(rows)}")

        # normalize column names (Phase I uses "sym" instead of "symbol")
        for r in rows:
            if "sym" in r and "symbol" not in r:
                r["symbol"] = r["sym"]
            if "signal_dt" in r and "signal_date" not in r:
                r["signal_date"] = r["signal_dt"]
            if "tp1" in r and "tp1_price" not in r:
                r["tp1_price"] = r["tp1"]
            if "tp2" in r and "tp2_price" not in r:
                r["tp2_price"] = r["tp2"]
            if "sl" in r and "sl_price" not in r:
                r["sl_price"] = r["sl"]

        # ── 3. Ensure Stock rows exist ────────────────────────────────────────
        unique_stocks = {}
        for r in rows:
            sym = r["symbol"].upper()
            if sym not in unique_stocks:
                unique_stocks[sym] = r.get("sector", "بنوك")

        stock_map: dict[str, int] = {}   # symbol → stock.id
        created_stocks = 0
        for sym, sector in unique_stocks.items():
            s = Stock.query.filter_by(symbol=sym).first()
            if not s:
                s = Stock(
                    symbol   = sym,
                    name_ar  = sym,          # placeholder — real name can be updated later
                    name_en  = sym,
                    sector   = sector,
                    is_sharia = False,
                    is_active = True,
                )
                db.session.add(s)
                created_stocks += 1
            stock_map[sym] = s
        db.session.flush()
        print(f"Stocks created: {created_stocks}, total mapped: {len(stock_map)}")

        # ── 4. Import opportunities ───────────────────────────────────────────
        created_opps = skipped_opps = 0
        for r in rows:
            sym          = r["symbol"].upper()
            signal_date  = date.fromisoformat(r["signal_date"])
            entry_price  = float(r["entry_price"] if r.get("entry_price") else r.get("ep", 0))

            stock = stock_map[sym]

            # idempotency check
            existing = Opportunity.query.filter_by(
                stock_id    = stock.id,
                run_date    = signal_date,
                entry_price = entry_price,
            ).first()
            if existing:
                skipped_opps += 1
                continue

            exit_reason = r["exit_reason"]
            outcome     = map_outcome(exit_reason)

            tp1 = _f(r, "tp1") or _f(r, "tp1_price")
            tp2 = _f(r, "tp2") or _f(r, "tp2_price")
            sl  = _f(r, "sl")  or _f(r, "sl_price")
            opp = Opportunity(
                stock_id   = stock.id,
                run_date   = signal_date,
                opp_type   = "Backtest",
                entry_price   = entry_price,
                tp1_price     = tp1,
                tp2_price     = tp2,
                sl_price      = sl,
                rr_ratio      = round((tp1 - entry_price) / (entry_price - sl), 2)
                                if tp1 and sl and sl < entry_price else None,
                max_hold_days = 20,
                radar_score   = _f(r, "score") or _f(r, "score_pct"),
                signal_quality = (
                    "HIGH"   if float(r["score_pct"]) >= 80 else
                    "MEDIUM" if float(r["score_pct"]) >= 65 else "LOW"
                ),
                # ── immutable Decision Moat snapshot ──────────────────────────
                feature_snapshot = {
                    "rsi":                   _f(r, "rsi"),
                    "adx":                   _f(r, "adx"),
                    "mfi":                   _f(r, "mfi"),
                    "score_pct":             _f(r, "score_pct"),
                    "contrib_ema_trend":     _i(r, "contrib_ema_trend"),
                    "contrib_rsi":           _i(r, "contrib_rsi"),
                    "contrib_bb_breakout":   _i(r, "contrib_bb_breakout"),
                    "contrib_obv":           _i(r, "contrib_obv"),
                    "contrib_adx":           _i(r, "contrib_adx"),
                    "contrib_vol_surge":     _i(r, "contrib_vol_surge"),
                    "contrib_bb_squeeze":    _i(r, "contrib_bb_squeeze"),
                    "contrib_mfi":           _i(r, "contrib_mfi"),
                    "contrib_rel_strength":  _i(r, "contrib_rel_strength"),
                    "sector":                r.get("sector", ""),
                    "investment":            _f(r, "investment"),
                    "shares":                _i(r, "shares"),
                },
                strategy_version_id = sv.id,
                # ── outcome (already known for backtest data) ─────────────────
                outcome     = outcome,
                is_active   = False,
                closed_at   = date.fromisoformat(r["exit_date"]) if r["exit_date"] else None,
                exit_price  = _f(r, "exit_price"),
                exit_reason = exit_reason,
                pnl_pct     = _f(r, "pnl_pct"),
                hold_days   = _i(r, "hold_days"),
            )
            db.session.add(opp)
            created_opps += 1

        if dry_run:
            db.session.rollback()
            print(f"\n[DRY RUN] Would create {created_opps} opportunities, skip {skipped_opps}")
        else:
            db.session.commit()
            print(f"\nDone. Imported {created_opps} opportunities, skipped {skipped_opps} duplicates")


def _f(row: dict, key: str) -> float | None:
    v = row.get(key, "")
    try:
        return float(v) if v not in ("", "None", "nan") else None
    except ValueError:
        return None


def _i(row: dict, key: str) -> int | None:
    v = _f(row, key)
    return int(v) if v is not None else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv",     required=True,       help="Path to trades.csv")
    parser.add_argument("--dry-run", action="store_true", help="Preview without committing")
    args = parser.parse_args()
    run(args.csv, dry_run=args.dry_run)
