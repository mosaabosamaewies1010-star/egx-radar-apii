"""
Explain Engine — template-based Arabic + English bullets.
Generates WhyThisScore content from ScoreBreakdown + Indicators.
"""
from app.services.indicators import Indicators
from app.services.radar_score import ScoreBreakdown


def generate_explain(
    ind: Indicators,
    bd: ScoreBreakdown,
    regime: str = "SIDEWAYS",
) -> dict[str, str]:
    """
    Returns {"ar": "bullet1\nbullet2\n...", "en": "bullet1\nbullet2\n..."}
    Max 5 bullets each — most impactful factors first.
    """
    bullets_ar = []
    bullets_en = []

    # ── Trend ──────────────────────────────────────────────────────────
    if bd.trend_score >= 18:
        bullets_ar.append(f"📈 الاتجاه قوي جداً — ADX عند {ind.adx:.0f} يشير إلى زخم صاعد مستمر")
        bullets_en.append(f"📈 Strong trend — ADX at {ind.adx:.0f} confirms sustained upward momentum")
    elif bd.trend_score >= 12:
        bullets_ar.append(f"📈 الاتجاه إيجابي — ADX عند {ind.adx:.0f} مع تأكيد من المتوسطات")
        bullets_en.append(f"📈 Positive trend — ADX at {ind.adx:.0f} supported by moving averages")
    elif bd.trend_score <= 4:
        bullets_ar.append(f"📉 ضعف الاتجاه — ADX عند {ind.adx:.0f} يعني أن السوق بلا اتجاه واضح")
        bullets_en.append(f"📉 Weak trend — ADX at {ind.adx:.0f} signals a directionless market")

    # ── Momentum ───────────────────────────────────────────────────────
    if 55 <= ind.rsi <= 68:
        bullets_ar.append(f"⚡ الزخم في المنطقة المثالية — RSI عند {ind.rsi:.0f} (ليس مبالغاً فيه)")
        bullets_en.append(f"⚡ Momentum in sweet spot — RSI at {ind.rsi:.0f} (not overextended)")
    elif ind.rsi > 75:
        bullets_ar.append(f"⚠️ مشتري بإفراط — RSI عند {ind.rsi:.0f}، احتمال تصحيح قريب")
        bullets_en.append(f"⚠️ Overbought — RSI at {ind.rsi:.0f}, pullback risk is elevated")
    elif ind.rsi < 35:
        bullets_ar.append(f"⚠️ بائع بإفراط — RSI عند {ind.rsi:.0f}، انتبه للارتداد المحتمل")
        bullets_en.append(f"⚠️ Oversold — RSI at {ind.rsi:.0f}, watch for a potential bounce")

    # ── Volume ─────────────────────────────────────────────────────────
    if ind.rvol > 1.5:
        bullets_ar.append(f"💹 حجم تداول قوي — {ind.rvol:.1f}x المعدل الطبيعي مع اهتمام كبير من المتداولين")
        bullets_en.append(f"💹 Strong volume — {ind.rvol:.1f}x average, significant trader interest")
    elif ind.rvol < 0.6:
        bullets_ar.append(f"🔇 حجم تداول منخفض — {ind.rvol:.1f}x المعدل، مشاركة ضعيفة في الحركة")
        bullets_en.append(f"🔇 Low volume — {ind.rvol:.1f}x average, weak participation in the move")

    if ind.obv_trend == "UP":
        bullets_ar.append("📊 OBV صاعد — الأموال الذكية تتراكم الأسهم")
        bullets_en.append("📊 Rising OBV — smart money accumulation detected")
    elif ind.obv_trend == "DOWN":
        bullets_ar.append("📊 OBV هابط — مؤشر على توزيع وبيع من الأموال الكبيرة")
        bullets_en.append("📊 Falling OBV — distribution by institutional sellers")

    # ── Volatility / Risk ──────────────────────────────────────────────
    if bd.risk_penalty >= 9:
        bullets_ar.append(f"🔴 مخاطر مرتفعة — ATR {ind.atr_pct:.1f}٪ يعني تذبذح يومي حاد، خصص وقف خسارة واسع")
        bullets_en.append(f"🔴 High risk — ATR {ind.atr_pct:.1f}% means wide daily swings, set wider stop-loss")
    elif bd.risk_penalty <= 2:
        bullets_ar.append(f"✅ مخاطر منخفضة — السهم مستقر نسبياً (ATR {ind.atr_pct:.1f}٪)")
        bullets_en.append(f"✅ Low risk — relatively stable stock (ATR {ind.atr_pct:.1f}%)")

    # ── Regime ────────────────────────────────────────────────────────
    regime_notes = {
        "BULL":          ("🟢 السوق في مرحلة صعود — يدعم الفرص الطويلة",
                          "🟢 Bull market environment — supports long opportunities"),
        "BEAR":          ("🔴 السوق في مرحلة هبوط — الدرع هابط يضغط على النتيجة",
                          "🔴 Bear market — regime multiplier reduces score"),
        "VOLATILE":      ("⚠️ السوق متقلب — الأسعار تتحرك بشكل متسارع ومتقلب",
                          "⚠️ Volatile market — sharp, erratic price movements"),
        "LOW_LIQUIDITY": ("⚠️ سيولة السوق منخفضة — صعوبة في الدخول والخروج",
                          "⚠️ Low market liquidity — entry/exit may be difficult"),
    }
    if regime in regime_notes:
        bullets_ar.append(regime_notes[regime][0])
        bullets_en.append(regime_notes[regime][1])

    # Cap at 5 bullets
    return {
        "ar": "\n".join(bullets_ar[:5]),
        "en": "\n".join(bullets_en[:5]),
    }
