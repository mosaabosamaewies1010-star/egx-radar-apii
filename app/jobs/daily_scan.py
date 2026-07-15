"""
Background job: scan all active stocks, compute Radar Scores, detect Opportunities.
Runs at 15:30 Cairo (after regime_job has committed today's regime).

Strategy Layer
--------------
PRIMARY  — SRA Engine (Smart Recovery Accumulation, Walk-Forward validated)
SECONDARY — Momentum Radar (ADX/RSI/Williams%, kept as Setup #2)

Both run every day. They write separate Opportunity records with different opp_type.
Old Momentum records: opp_type = "Breakout" | "Momentum" | "Swing" | "Sharia"
New SRA records:      opp_type = "SRA_A+"   | "SRA_A"   | "SRA_B"
"""
import logging
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)


def run_daily_scan(app) -> None:
    with app.app_context():
        try:
            from app import db
            from app.models.stock import Stock
            from app.models.score import RadarScoreHistory
            from app.models.opportunity import Opportunity
            from app.models.regime import MarketRegimeHistory
            from app.models.scan_log import ScanLog

            today = date.today()
            scan_log = ScanLog(run_date=today, status="running")
            db.session.add(scan_log)
            db.session.commit()
            from app.services.indicators import compute_indicators
            from app.services.radar_score import compute_radar_score
            from app.services.opportunity import compute_opportunity
            from app.services.explain import generate_explain
            from app.utils.data_fetcher import (
                fetch_ohlcv, fetch_multiple, compute_adt, assess_data_quality,
            )

            # SRA Engine — imported with guard so old scan still runs if unavailable
            try:
                from app.services.sra_engine import (
                    detect_sra_setup, compute_sra_breadth, compute_sector_slope,
                )
                from app.services.knowledge_base import query_similar_setups
                _SRA_AVAILABLE = True
            except ImportError:
                logger.warning("daily_scan: sra_engine not available — skipping SRA pass")
                _SRA_AVAILABLE = False

            stocks = Stock.query.filter_by(is_active=True).all()

            # ── Regime (old system — kept for Momentum pass) ─────────────────
            regime_rec = (
                MarketRegimeHistory.query
                .order_by(MarketRegimeHistory.run_date.desc())
                .first()
            )
            momentum_regime = regime_rec.regime if regime_rec else "SIDEWAYS"
            logger.info(
                "daily_scan: %d stocks (momentum_regime=%s)",
                len(stocks), momentum_regime,
            )

            # ── Pre-fetch all data for SRA breadth calculation ────────────────
            # We need the full universe to compute % above EMA50.
            sra_regime   = "neutral"
            breadth_pct  = 50.0
            all_dfs: dict[str, object] = {}

            if _SRA_AVAILABLE:
                symbols = [s.symbol for s in stocks]
                logger.info("daily_scan: pre-fetching %d tickers for SRA breadth...", len(symbols))
                all_dfs = fetch_multiple(symbols, period="6mo")
                # 6mo ≈ 126 trading days — enough for EMA50 + scan window + buffer
                valid_dfs = {sym: df for sym, df in all_dfs.items() if df is not None}
                if valid_dfs:
                    sra_regime, breadth_pct = compute_sra_breadth(valid_dfs)
                logger.info(
                    "daily_scan: SRA regime=%s breadth=%.1f%% (%d/%d tickers have data)",
                    sra_regime, breadth_pct, len(valid_dfs), len(symbols),
                )

            # ── Save SRA regime to DB so /api/market/regime returns real data ──
            if _SRA_AVAILABLE and valid_dfs:
                regime_map = {
                    "bull":    ("BULL",     75.0),
                    "bear":    ("BEAR",     70.0),
                    "neutral": ("SIDEWAYS", 55.0),
                }
                db_regime, db_conf = regime_map.get(sra_regime, ("SIDEWAYS", 55.0))

                adv = dec = 0
                for df in valid_dfs.values():
                    try:
                        col = next(c for c in df.columns if c.lower() == 'close')
                        if len(df) >= 2:
                            if df[col].iloc[-1] > df[col].iloc[-2]:
                                adv += 1
                            elif df[col].iloc[-1] < df[col].iloc[-2]:
                                dec += 1
                    except (StopIteration, Exception):
                        pass
                unch = len(valid_dfs) - adv - dec

                reason_map = {
                    "bull":    (f"السوق في مرحلة ثورية — {breadth_pct:.0f}% من الأسهم فوق EMA50",
                                f"Bullish market — {breadth_pct:.0f}% of stocks above EMA50"),
                    "bear":    (f"السوق في مرحلة هبوطية — {breadth_pct:.0f}% من الأسهم فوق EMA50",
                                f"Bearish market — {breadth_pct:.0f}% of stocks above EMA50"),
                    "neutral": (f"السوق في حالة تعادل — {breadth_pct:.0f}% من الأسهم فوق EMA50",
                                f"Sideways market — {breadth_pct:.0f}% of stocks above EMA50"),
                }
                reason_ar, reason_en = reason_map.get(sra_regime, ("غير محدد", "Unknown"))

                existing_regime = MarketRegimeHistory.query.filter_by(run_date=today).first()
                if not existing_regime:
                    db.session.add(MarketRegimeHistory(
                        run_date   = today,
                        regime     = db_regime,
                        confidence = db_conf,
                        advancing  = adv,
                        declining  = dec,
                        unchanged  = unch,
                        reason_ar  = reason_ar,
                        reason_en  = reason_en,
                    ))
                    db.session.commit()
                    logger.info(
                        "daily_scan: saved regime %s (conf=%.0f%%, adv=%d, dec=%d)",
                        db_regime, db_conf, adv, dec,
                    )

            # ── Group stocks by sector for sector slope ───────────────────────
            # sector_peers[sector] = list of DataFrames for that sector
            sector_peers: dict[str, list] = {}
            if _SRA_AVAILABLE:
                for stock in stocks:
                    sec = getattr(stock, "sector", None) or "unknown"
                    df  = all_dfs.get(stock.symbol)
                    if df is not None:
                        sector_peers.setdefault(sec, []).append(df)

            # ──────────────────────────────────────────────────────────────────
            # Main scan loop
            # ──────────────────────────────────────────────────────────────────
            success = skip = fail = 0

            for stock in stocks:
                try:
                    if RadarScoreHistory.query.filter_by(
                        stock_id=stock.id, run_date=today
                    ).first():
                        skip += 1
                        continue

                    # ── MOMENTUM PASS (old system — unchanged) ────────────────
                    df = all_dfs.get(stock.symbol) if all_dfs else None
                    if df is None:
                        df = fetch_ohlcv(stock.symbol)

                    if df is None:
                        logger.warning("daily_scan: no data for %s", stock.symbol)
                        fail += 1
                        continue

                    quality = assess_data_quality(df, stock.symbol)
                    adt     = compute_adt(df)
                    ind     = compute_indicators(df, quality)

                    if ind is None:
                        logger.warning(
                            "daily_scan: insufficient indicators for %s", stock.symbol
                        )
                        fail += 1
                        continue

                    bd         = compute_radar_score(ind, adt, regime=momentum_regime)
                    explain    = generate_explain(ind, bd, momentum_regime)
                    opp_result = compute_opportunity(
                        ind, bd, is_sharia=stock.is_sharia, regime=momentum_regime
                    )

                    score_rec = RadarScoreHistory(
                        stock_id          = stock.id,
                        run_date          = today,
                        score             = bd.final_score,
                        trend_score       = bd.trend_score,
                        momentum_score    = bd.momentum_score,
                        liquidity_score   = bd.liquidity_score,
                        volume_score      = bd.volume_score,
                        sector_score      = bd.sector_score,
                        fundamental_score = bd.fundamental_score,
                        risk_penalty      = bd.risk_penalty,
                        regime_multiplier = bd.regime_multiplier,
                        adx               = ind.adx,
                        rsi               = ind.rsi,
                        macd              = ind.macd,
                        macd_signal       = ind.macd_signal,
                        atr_pct           = ind.atr_pct,
                        rvol              = ind.rvol,
                        ma20              = ind.ma20,
                        ma50              = ind.ma50,
                        ma200             = ind.ma200,
                        obv_trend         = ind.obv_trend,
                        explain_ar        = explain["ar"],
                        explain_en        = explain["en"],
                        data_quality      = quality,
                    )
                    db.session.add(score_rec)

                    if opp_result:
                        db.session.add(Opportunity(
                            stock_id       = stock.id,
                            run_date       = today,
                            opp_type       = opp_result.opp_type,
                            entry_price    = opp_result.entry_price,
                            tp1_price      = opp_result.tp1_price,
                            tp2_price      = opp_result.tp2_price,
                            sl_price       = opp_result.sl_price,
                            rr_ratio       = opp_result.rr_ratio,
                            max_hold_days  = opp_result.max_hold_days,
                            radar_score    = bd.final_score,
                            signal_quality = opp_result.signal_quality,
                            outcome        = "PENDING",
                        ))

                    # ── SRA PASS (new primary engine) ─────────────────────────
                    if _SRA_AVAILABLE:
                        sec             = getattr(stock, "sector", None) or "unknown"
                        peers           = sector_peers.get(sec, [])
                        sector_slope    = compute_sector_slope(peers)
                        sector_positive = sector_slope > 0

                        sra = detect_sra_setup(
                            df              = df,
                            regime          = sra_regime,
                            breadth_pct     = breadth_pct,
                            sector_positive = sector_positive,
                            min_grade       = "B",
                            ticker          = stock.symbol,
                        )

                        if sra is not None:
                            sra.ticker = stock.symbol

                            sl  = min(sra.fast_sl, sra.balanced_sl)
                            rr1 = ((sra.fast_tp - sra.entry_price) /
                                   (sra.entry_price - sl)) if sra.entry_price > sl else None

                            grade_quality = {"A+": "HIGH", "A": "MEDIUM", "B": "LOW"}

                            # ── Enrich with real KB stats ─────────────────────
                            kb = query_similar_setups(
                                db,
                                grade           = sra.grade,
                                regime          = sra_regime,
                                sector_positive = sector_positive,
                            )
                            sra.similar_cases        = kb["similar_cases"]
                            sra.historical_win_rate  = kb["historical_win_rate"]
                            sra.avg_return           = kb["avg_return"]

                            snap = sra.feature_snapshot()
                            snap.update({
                                "strategy_version":  "SRA_v2",
                                "median_return":     kb["median_return"],
                                "best_case":         kb["best_case"],
                                "worst_case":        kb["worst_case"],
                                "avg_win":           kb["avg_win"],
                                "avg_loss":          kb["avg_loss"],
                                "kb_confidence":     kb["confidence"],
                            })

                            db.session.add(Opportunity(
                                stock_id         = stock.id,
                                run_date         = today,
                                opp_type         = sra.opp_type,
                                entry_price      = sra.entry_price,
                                tp1_price        = sra.fast_tp,
                                tp2_price        = sra.balanced_tp,
                                sl_price         = sl,
                                rr_ratio         = round(rr1, 2) if rr1 else None,
                                max_hold_days    = sra.balanced_max_bars,
                                radar_score      = sra.score,
                                signal_quality   = grade_quality.get(sra.grade, "LOW"),
                                outcome          = "PENDING",
                                feature_snapshot = snap,
                            ))
                            logger.info(
                                "daily_scan: SRA %s — %s (score=%.0f)",
                                stock.symbol, sra.opp_type, sra.score,
                            )

                    db.session.commit()
                    success += 1

                except Exception:
                    db.session.rollback()
                    logger.warning(
                        "daily_scan: error for %s", stock.symbol, exc_info=True
                    )
                    fail += 1

            logger.info(
                "daily_scan: done — success=%d, skip=%d, fail=%d",
                success, skip, fail,
            )

            # ── Update ScanLog ───────────────────────────────────────────────
            sra_count = Opportunity.query.filter(
                Opportunity.opp_type.like("SRA_%"), Opportunity.run_date == today
            ).count()
            momentum_count = Opportunity.query.filter(
                ~Opportunity.opp_type.like("SRA_%"), Opportunity.run_date == today
            ).count()
            kb_size = Opportunity.query.filter(
                Opportunity.opp_type.like("SRA_%"),
                Opportunity.outcome.in_(["WIN", "LOSS"])
            ).count()

            scan_log.stocks_scanned   = success + skip
            scan_log.sra_signals      = sra_count
            scan_log.momentum_signals = momentum_count
            scan_log.kb_size          = kb_size
            scan_log.regime           = sra_regime if _SRA_AVAILABLE else momentum_regime
            scan_log.breadth_pct      = breadth_pct if _SRA_AVAILABLE else None
            scan_log.status           = "success" if fail == 0 else "partial"
            scan_log.finished_at      = datetime.now(timezone.utc)
            db.session.commit()

        except Exception:
            logger.exception("daily_scan: top-level error")
            try:
                scan_log.status        = "failed"
                scan_log.error_message = "top-level exception — see server logs"
                scan_log.finished_at   = datetime.now(timezone.utc)
                db.session.commit()
            except Exception:
                pass
