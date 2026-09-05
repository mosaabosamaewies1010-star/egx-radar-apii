"""
Background job: scan all active stocks, compute Radar Scores, detect Opportunities.
Runs at 15:30 Cairo (after regime_job has committed today's regime).

Core Engine v1.0 (FROZEN — لا تغير المنطق ده لمدة 6 شهور)
-----------------------------------------------------------
Priority per stock — only ONE signal fires per day (Stage/Trend/Vol chain):
  1st  Stage Breakout  ⭐⭐⭐⭐⭐ — TREND_CROSS today + VOL spike (60b) | Test PF = 2.075
  2nd  Trend Initiation⭐⭐⭐⭐  — Fresh EMA cross + ADX≥20 + RSI>50   | Test PF = 1.644
       (A+/A grades only — Grade B PF < 1.0 in backtest → excluded)
  3rd  Volume Radar    ⭐⭐⭐    — VOL Expansion, no trend yet          | Discovery/Watch only

SRA Engine (Engine Comparison pass — SEPARATE from priority chain):
  SRA runs independently on ALL stocks after the main loop.
  A stock can have both a STAGE_/TREND_ signal AND an SRA_ signal on the same day.
  Purpose: Engine Comparison v1 — measure SRA vs Stage/Trend overlap and alpha.

RadarScoreHistory is still recorded for every stock (used by stock detail page).
Old Momentum engine no longer generates new Opportunity records.
"""
import logging
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def run_daily_scan(app) -> None:
    with app.app_context():
        scan_log = None
        try:
            from app import db
            from app.models.stock import Stock
            from app.models.score import RadarScoreHistory
            from app.models.opportunity import Opportunity
            from app.models.regime import MarketRegimeHistory
            from app.models.scan_log import ScanLog
            from app.models.strategy_version import StrategyVersion

            try:
                db.create_all()
            except Exception as _ce:
                logger.warning("daily_scan: db.create_all() warning: %s", _ce)

            today = date.today()

            # Look up current strategy version (v1.0) — used to tag every new signal
            v1 = StrategyVersion.query.filter_by(version="v1.0").first()
            v1_id = v1.id if v1 else None

            try:
                scan_log = ScanLog(run_date=today, status="running")
                db.session.add(scan_log)
                db.session.commit()
            except Exception as _sle:
                db.session.rollback()
                logger.warning("daily_scan: could not create ScanLog: %s", _sle)
                scan_log = None

            # Cap on live yf.Ticker(...).info calls — prevents memory spikes on Render free tier
            MAX_FUNDAMENTALS_PER_RUN = 40
            fundamentals_fetched_this_run = 0

            from app.services.indicators import compute_indicators
            from app.services.radar_score import compute_radar_score
            from app.services.explain import generate_explain
            from app.utils.data_fetcher import (
                fetch_ohlcv, fetch_multiple, fetch_fundamentals, compute_adt, assess_data_quality,
            )

            # Breadth calculation + SRA Engine (Engine Comparison pass)
            try:
                from app.services.sra_engine import compute_sra_breadth, detect_sra_setup
                _BREADTH_AVAILABLE = True
                _SRA_AVAILABLE = True
            except ImportError:
                _BREADTH_AVAILABLE = False
                _SRA_AVAILABLE = False
                logger.warning("daily_scan: sra_engine not available — breadth defaults to 50%%, SRA skipped")

            # Engine Comparison Logger
            try:
                from app.models.engine_comparison_log import EngineComparisonLog
                _CMP_LOG_AVAILABLE = True
            except ImportError:
                _CMP_LOG_AVAILABLE = False
                logger.warning("daily_scan: EngineComparisonLog not available — comparison logging skipped")

            def _log_cmp(engine, signal_type, opp_id, entry, ref_price,
                         tp1, tp2, sl, rr, hold, score, grade, snap):
                """Write one canonical comparison row.

                ref_price — always df["close"].iloc[-1] at scan time.
                    For STAGE/TREND/VOL_RADAR this equals entry_price.
                    For SRA it differs (entry is swing-low based); ref_price
                    is what the update job uses for ALL forward-return math.
                """
                if not _CMP_LOG_AVAILABLE:
                    return
                try:
                    db.session.add(EngineComparisonLog(
                        setup_id        = EngineComparisonLog.build_setup_id(today, stock.symbol),
                        signal_date     = today,
                        symbol          = stock.symbol,
                        engine          = engine,
                        signal_type     = signal_type,
                        opportunity_id  = opp_id,
                        entry_price     = entry,
                        reference_price = ref_price,
                        tp1_price       = tp1,
                        tp2_price       = tp2,
                        sl_price        = sl,
                        rr_ratio        = rr,
                        max_hold_days   = hold,
                        score           = score,
                        grade           = grade,
                        regime          = snap.get("regime"),
                        breadth_pct     = snap.get("breadth_pct"),
                        rvol            = snap.get("rvol"),
                        adx             = snap.get("adx"),
                        rsi             = snap.get("rsi"),
                    ))
                except Exception:
                    logger.warning("daily_scan: _log_cmp failed for %s", stock.symbol, exc_info=True)

            # Stage Breakout Engine (Primary ⭐⭐⭐⭐⭐) — PF 2.075
            try:
                from app.services.stage_engine import detect_stage_breakout
                _STAGE_AVAILABLE = True
            except ImportError:
                logger.warning("daily_scan: stage_engine not available — skipping STAGE pass")
                _STAGE_AVAILABLE = False

            # Trend Initiation Engine (Secondary ⭐⭐⭐⭐, A+/A only) — PF 1.644
            try:
                from app.services.trend_engine import detect_trend_initiation
                _TREND_AVAILABLE = True
            except ImportError:
                logger.warning("daily_scan: trend_engine not available — skipping TREND pass")
                _TREND_AVAILABLE = False

            # Volume Radar Engine (Discovery ⭐⭐⭐) — watch signal, not a buy signal
            try:
                from app.services.volume_radar_engine import detect_volume_radar
                _VOL_RADAR_AVAILABLE = True
            except ImportError:
                logger.warning("daily_scan: volume_radar_engine not available — skipping VOL_RADAR pass")
                _VOL_RADAR_AVAILABLE = False

            stocks = Stock.query.filter_by(is_active=True).all()

            # ── Pre-fetch all OHLCV (6 months) ────────────────────────────────
            # Used for: (1) per-stock fast df lookup in main loop
            #           (2) breadth_pct calculation passed to Stage + Trend engines
            symbols = [s.symbol for s in stocks]
            logger.info("daily_scan: pre-fetching %d tickers...", len(symbols))
            all_dfs = fetch_multiple(symbols, period="6mo")

            valid_dfs  = {sym: df for sym, df in all_dfs.items() if df is not None}
            breadth_pct = 50.0
            sra_regime  = "neutral"

            if _BREADTH_AVAILABLE and valid_dfs:
                sra_regime, breadth_pct = compute_sra_breadth(valid_dfs)

            logger.info(
                "daily_scan: %d stocks | breadth=%.1f%% | regime=%s",
                len(stocks), breadth_pct, sra_regime,
            )

            # ── Save market regime → DB (admin page + regime detection) ───────
            if valid_dfs:
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
                    try:
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
                    except Exception:
                        db.session.rollback()
                        logger.warning("daily_scan: regime insert race — another thread won, continuing")

            # Legacy regime label for RadarScoreHistory (kept for score explanation text)
            regime_rec      = MarketRegimeHistory.query.order_by(MarketRegimeHistory.run_date.desc()).first()
            momentum_regime = regime_rec.regime if regime_rec else "SIDEWAYS"

            # ──────────────────────────────────────────────────────────────────
            # Main scan loop
            # ──────────────────────────────────────────────────────────────────
            success = skip = fail = 0

            for stock in stocks:
                try:
                    # ── OHLCV ─────────────────────────────────────────────────
                    df = all_dfs.get(stock.symbol)
                    if df is None:
                        df = fetch_ohlcv(stock.symbol)
                    if df is None:
                        logger.warning("daily_scan: no data for %s", stock.symbol)
                        fail += 1
                        continue

                    # ── Price snapshot ─────────────────────────────────────────
                    adt_val = compute_adt(df)
                    try:
                        last = df.iloc[-1]
                        stock.day_open         = float(last["open"])
                        stock.day_high         = float(last["high"])
                        stock.day_low          = float(last["low"])
                        stock.last_price       = float(last["close"])
                        stock.last_volume      = int(last["volume"])
                        stock.last_adt         = adt_val
                        stock.price_updated_at = datetime.now(timezone.utc)
                        if len(df) >= 2:
                            prev_close = float(df["close"].iloc[-2])
                            if prev_close > 0:
                                stock.last_change_amt = round(stock.last_price - prev_close, 4)
                                stock.last_change_pct = round(stock.last_change_amt / prev_close * 100, 2)
                    except Exception:
                        logger.warning("daily_scan: price snapshot failed for %s", stock.symbol, exc_info=True)

                    # ── Fundamentals (weekly cap) ──────────────────────────────
                    stale = (
                        stock.fundamentals_updated_at is None
                        or stock.fundamentals_updated_at < datetime.now(timezone.utc) - timedelta(days=6)
                    )
                    if stale and fundamentals_fetched_this_run >= MAX_FUNDAMENTALS_PER_RUN:
                        stale = False
                    if stale:
                        fundamentals_fetched_this_run += 1
                        try:
                            fnd = fetch_fundamentals(stock.symbol)
                            if fnd:
                                stock.market_cap              = fnd.get("market_cap")
                                stock.pe_ratio                = fnd.get("pe_ratio")
                                stock.eps                     = fnd.get("eps")
                                stock.dividend_yield          = fnd.get("dividend_yield")
                                stock.week52_high             = fnd.get("week52_high")
                                stock.week52_low              = fnd.get("week52_low")
                                stock.book_value              = fnd.get("book_value")
                                stock.fundamentals_updated_at = datetime.now(timezone.utc)
                        except Exception:
                            logger.warning("daily_scan: fundamentals fetch failed for %s", stock.symbol, exc_info=True)

                    # ── RadarScoreHistory (all stocks — needed by stock detail page) ─
                    already_scored = RadarScoreHistory.query.filter_by(
                        stock_id=stock.id, run_date=today
                    ).first()

                    if not already_scored:
                        quality = assess_data_quality(df, stock.symbol)
                        ind     = compute_indicators(df, quality)

                        if ind is None:
                            logger.warning("daily_scan: insufficient indicators for %s", stock.symbol)
                            fail += 1
                        else:
                            bd      = compute_radar_score(ind, adt_val, regime=momentum_regime)
                            explain = generate_explain(ind, bd, momentum_regime)

                            db.session.add(RadarScoreHistory(
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
                            ))
                            success += 1
                    else:
                        skip += 1

                    # ══════════════════════════════════════════════════════════
                    # CORE ENGINE v1.0 — Priority Logic (FROZEN)
                    # Stage → Trend (A+/A) → Volume Radar
                    # ══════════════════════════════════════════════════════════

                    # ── 1. STAGE BREAKOUT (Primary ⭐⭐⭐⭐⭐) ──────────────────
                    stage_today = Opportunity.query.filter(
                        Opportunity.stock_id == stock.id,
                        Opportunity.run_date == today,
                        Opportunity.opp_type.like("STAGE_%"),
                    ).first()

                    if stage_today:
                        # Already has Stage signal — skip lower tiers
                        db.session.commit()
                        continue

                    if _STAGE_AVAILABLE:
                        stage = detect_stage_breakout(
                            df          = df,
                            breadth_pct = breadth_pct,
                            ticker      = stock.symbol,
                        )
                        if stage is not None:
                            s_sl  = min(stage.fast_sl, stage.balanced_sl)
                            s_rr1 = (
                                (stage.fast_tp - stage.entry_price) / (stage.entry_price - s_sl)
                                if stage.entry_price > s_sl else None
                            )
                            stage_snap = stage.feature_snapshot()
                            stage_snap["regime"]      = momentum_regime   # regime at signal time
                            stage_snap["breadth_pct"] = round(breadth_pct, 1)
                            _stage_opp = Opportunity(
                                stock_id             = stock.id,
                                run_date             = today,
                                opp_type             = stage.opp_type,
                                entry_price          = stage.entry_price,
                                tp1_price            = stage.fast_tp,
                                tp2_price            = stage.balanced_tp,
                                sl_price             = s_sl,
                                rr_ratio             = round(s_rr1, 2) if s_rr1 else None,
                                max_hold_days        = stage.balanced_max_bars,
                                radar_score          = stage.stage_score,
                                signal_quality       = "HIGH" if stage.strength == "STRONG" else "MEDIUM",
                                outcome              = "PENDING",
                                feature_snapshot     = stage_snap,
                                strategy_version_id  = v1_id,
                            )
                            db.session.add(_stage_opp)
                            db.session.flush()
                            _log_cmp(
                                "STAGE", stage.opp_type, _stage_opp.id,
                                stage.entry_price, stage.entry_price,   # entry == ref for STAGE
                                stage.fast_tp, stage.balanced_tp, s_sl,
                                round(s_rr1, 2) if s_rr1 else None, stage.balanced_max_bars,
                                stage.stage_score, stage.strength, stage_snap,
                            )
                            logger.info(
                                "daily_scan: STAGE %s — %s (score=%.0f vol_age=%db)",
                                stock.symbol, stage.opp_type, stage.stage_score, stage.vol_age_bars,
                            )
                            db.session.commit()
                            continue  # Stage wins → skip Trend + Volume for this stock

                    # ── 2. TREND INITIATION (Secondary ⭐⭐⭐⭐, A+/A only) ─────
                    # Grade B is excluded — backtest shows PF < 1.0
                    trend_today = Opportunity.query.filter(
                        Opportunity.stock_id == stock.id,
                        Opportunity.run_date == today,
                        Opportunity.opp_type.like("TREND_%"),
                    ).first()

                    if trend_today:
                        # Already has Trend signal — skip Volume Radar
                        db.session.commit()
                        continue

                    if _TREND_AVAILABLE:
                        trend = detect_trend_initiation(
                            df          = df,
                            breadth_pct = breadth_pct,
                            ticker      = stock.symbol,
                        )
                        if trend is not None and trend.grade in ("A+", "A"):
                            t_sl  = min(trend.fast_sl, trend.balanced_sl)
                            t_rr1 = (
                                (trend.fast_tp - trend.entry_price) / (trend.entry_price - t_sl)
                                if trend.entry_price > t_sl else None
                            )
                            trend_snap = trend.feature_snapshot()
                            trend_snap["regime"]      = momentum_regime   # regime at signal time
                            trend_snap["breadth_pct"] = round(breadth_pct, 1)
                            _trend_opp = Opportunity(
                                stock_id             = stock.id,
                                run_date             = today,
                                opp_type             = trend.opp_type,
                                entry_price          = trend.entry_price,
                                tp1_price            = trend.fast_tp,
                                tp2_price            = trend.balanced_tp,
                                sl_price             = t_sl,
                                rr_ratio             = round(t_rr1, 2) if t_rr1 else None,
                                max_hold_days        = trend.balanced_max_bars,
                                radar_score          = trend.trend_strength,
                                signal_quality       = "HIGH" if trend.grade == "A+" else "MEDIUM",
                                outcome              = "PENDING",
                                feature_snapshot     = trend_snap,
                                strategy_version_id  = v1_id,
                            )
                            db.session.add(_trend_opp)
                            db.session.flush()
                            _log_cmp(
                                "TREND", trend.opp_type, _trend_opp.id,
                                trend.entry_price, trend.entry_price,   # entry == ref for TREND
                                trend.fast_tp, trend.balanced_tp, t_sl,
                                round(t_rr1, 2) if t_rr1 else None, trend.balanced_max_bars,
                                trend.trend_strength, trend.grade, trend_snap,
                            )
                            logger.info(
                                "daily_scan: TREND %s — %s (strength=%.0f grade=%s)",
                                stock.symbol, trend.opp_type, trend.trend_strength, trend.grade,
                            )
                            db.session.commit()
                            continue  # Trend wins → skip Volume for this stock

                    # ── 3. VOLUME RADAR (Discovery ⭐⭐⭐) ──────────────────────
                    # Watch signal only — السهم في مرحلة تجميع، راقبه للـ Stage القادم
                    vol_today = Opportunity.query.filter(
                        Opportunity.stock_id == stock.id,
                        Opportunity.run_date == today,
                        Opportunity.opp_type == "VOL_RADAR",
                    ).first()

                    if not vol_today and _VOL_RADAR_AVAILABLE:
                        vol = detect_volume_radar(df=df, adt=adt_val, ticker=stock.symbol)
                        if vol is not None:
                            vol_snap = vol.feature_snapshot()
                            vol_snap["regime"]      = momentum_regime   # regime at signal time
                            vol_snap["breadth_pct"] = round(breadth_pct, 1)
                            _vol_opp = Opportunity(
                                stock_id             = stock.id,
                                run_date             = today,
                                opp_type             = "VOL_RADAR",
                                entry_price          = vol.close,
                                tp1_price            = None,
                                tp2_price            = None,
                                sl_price             = None,
                                rr_ratio             = None,
                                max_hold_days        = 60,
                                radar_score          = vol.vol_rvol * 10,
                                signal_quality       = "LOW",
                                outcome              = "PENDING",
                                feature_snapshot     = vol_snap,
                                strategy_version_id  = v1_id,
                            )
                            db.session.add(_vol_opp)
                            db.session.flush()
                            _log_cmp(
                                "VOL_RADAR", "VOL_RADAR", _vol_opp.id,
                                vol.close, vol.close,   # entry == ref for VOL_RADAR
                                None, None, None, None, 60,
                                vol.vol_rvol * 10, None, vol_snap,
                            )
                            logger.info(
                                "daily_scan: VOL_RADAR %s (vol_age=%db rvol=%.1f gap=%.1f%%)",
                                stock.symbol, vol.vol_age_bars, vol.vol_rvol, vol.ema_gap_pct,
                            )

                    db.session.commit()

                except Exception:
                    db.session.rollback()
                    logger.warning("daily_scan: error for %s", stock.symbol, exc_info=True)
                    fail += 1

            logger.info("daily_scan: done — success=%d, skip=%d, fail=%d", success, skip, fail)

            # ══════════════════════════════════════════════════════════════════
            # SRA ENGINE — Independent pass for Engine Comparison v1
            # Runs on ALL stocks regardless of Stage/Trend/Vol signals.
            # ══════════════════════════════════════════════════════════════════
            sra_new = 0
            if _SRA_AVAILABLE:
                for stock in stocks:
                    try:
                        df = all_dfs.get(stock.symbol)
                        if df is None:
                            continue
                        existing_sra = Opportunity.query.filter(
                            Opportunity.stock_id == stock.id,
                            Opportunity.run_date == today,
                            Opportunity.opp_type.like("SRA_%"),
                        ).first()
                        if existing_sra:
                            continue
                        sra = detect_sra_setup(
                            df=df,
                            ticker=stock.symbol,
                            breadth_pct=breadth_pct,
                            regime=sra_regime,
                            sector_positive=True,
                            min_grade="A",
                        )
                        if sra is not None and sra.grade in ("A+", "A"):
                            s_sl = min(sra.fast_sl, sra.balanced_sl)
                            s_rr = (
                                (sra.fast_tp - sra.entry_price) / (sra.entry_price - s_sl)
                                if sra.entry_price > s_sl else None
                            )
                            snap = sra.feature_snapshot()
                            snap["regime"]      = momentum_regime
                            snap["breadth_pct"] = round(breadth_pct, 1)
                            _sra_opp = Opportunity(
                                stock_id            = stock.id,
                                run_date            = today,
                                opp_type            = sra.opp_type,
                                entry_price         = sra.entry_price,
                                tp1_price           = sra.fast_tp,
                                tp2_price           = sra.balanced_tp,
                                sl_price            = s_sl,
                                rr_ratio            = round(s_rr, 2) if s_rr else None,
                                max_hold_days       = sra.balanced_max_bars,
                                radar_score         = sra.score,
                                signal_quality      = "HIGH" if sra.grade == "A+" else "MEDIUM",
                                outcome             = "PENDING",
                                feature_snapshot    = snap,
                                strategy_version_id = v1_id,
                            )
                            db.session.add(_sra_opp)
                            db.session.flush()
                            # SRA entry_price is swing-low based (historical).
                            # ref_price = today's close so forward returns are comparable.
                            _sra_ref = float(df["close"].iloc[-1])
                            _log_cmp(
                                "SRA", sra.opp_type, _sra_opp.id,
                                sra.entry_price, _sra_ref,   # ref != entry for SRA
                                sra.fast_tp, sra.balanced_tp, s_sl,
                                round(s_rr, 2) if s_rr else None, sra.balanced_max_bars,
                                sra.score, sra.grade, snap,
                            )
                            db.session.commit()
                            sra_new += 1
                            logger.info(
                                "daily_scan: SRA %s — %s (score=%.0f rvol=%.1f)",
                                stock.symbol, sra.opp_type, sra.score, sra.rvol_spike,
                            )
                    except Exception:
                        db.session.rollback()
                        logger.warning("daily_scan: SRA error for %s", stock.symbol, exc_info=True)
            logger.info("daily_scan: SRA new signals=%d", sra_new)

            # ── Summary counts ─────────────────────────────────────────────────
            stage_count = Opportunity.query.filter(
                Opportunity.opp_type.like("STAGE_%"), Opportunity.run_date == today
            ).count()
            trend_count = Opportunity.query.filter(
                Opportunity.opp_type.like("TREND_%"), Opportunity.run_date == today
            ).count()
            vol_radar_count = Opportunity.query.filter(
                Opportunity.opp_type == "VOL_RADAR", Opportunity.run_date == today
            ).count()

            stage_syms = [
                o.stock.symbol for o in Opportunity.query.filter(
                    Opportunity.opp_type.like("STAGE_%"), Opportunity.run_date == today
                ).all()
            ]
            trend_syms = [
                o.stock.symbol for o in Opportunity.query.filter(
                    Opportunity.opp_type.like("TREND_%"), Opportunity.run_date == today
                ).all()
            ]

            logger.info("daily_scan: ===== CORE ENGINE v1.0 SUMMARY =====")
            logger.info("daily_scan: STAGE (%d): %s", stage_count, ", ".join(stage_syms) or "-")
            logger.info("daily_scan: TREND (%d): %s", trend_count, ", ".join(trend_syms) or "-")
            logger.info("daily_scan: VOL_RADAR (%d)", vol_radar_count)
            logger.info(
                "daily_scan: scanned=%d success=%d skip=%d fail=%d",
                success + skip + fail, success, skip, fail,
            )
            logger.info("daily_scan: ========================================")

            if scan_log is not None:
                scan_log.stocks_scanned   = success + skip + fail
                scan_log.sra_signals      = stage_count + trend_count + vol_radar_count
                scan_log.momentum_signals = stage_count
                scan_log.kb_size          = 0
                scan_log.regime           = sra_regime
                scan_log.breadth_pct      = breadth_pct
                scan_log.status           = "success" if fail == 0 else "partial"
                scan_log.finished_at      = datetime.now(timezone.utc)
                db.session.commit()

        except Exception as _top_exc:
            import traceback
            _tb = traceback.format_exc()
            logger.exception("daily_scan: top-level error")
            if scan_log is not None:
                try:
                    scan_log.status        = "failed"
                    scan_log.error_message = str(_top_exc)[:1000] + "\n---\n" + _tb[-1500:]
                    scan_log.finished_at   = datetime.now(timezone.utc)
                    db.session.commit()
                except Exception:
                    pass
