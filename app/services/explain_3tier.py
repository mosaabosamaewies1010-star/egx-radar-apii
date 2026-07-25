"""
Explainable AI — 3-tier engine.
Generates Arabic bullet list from feature_snapshot for Stage / Trend / VOL_RADAR signals.
Returns list[str] — max 5 bullets, most important first.
"""
from app.models.opportunity import Opportunity


def explain_signal(opp: Opportunity) -> list[str]:
    snap  = opp.feature_snapshot or {}
    if not isinstance(snap, dict):
        snap = {}
    otype  = opp.opp_type or ""
    regime = snap.get("regime", "SIDEWAYS")

    if otype.startswith("STAGE_"):
        return _explain_stage(snap, regime)
    if otype.startswith("TREND_"):
        return _explain_trend(snap, regime)
    if otype == "VOL_RADAR":
        return _explain_vol(snap, regime)
    return []


# ── Stage ──────────────────────────────────────────────────────────────────────

def _explain_stage(snap: dict, regime: str) -> list[str]:
    bullets = []

    stage_score = snap.get("stage_score", 0)
    vol_age     = snap.get("vol_age_bars", 0)
    vol_rvol    = snap.get("vol_rvol", 0)
    adx         = snap.get("adx", 0)
    rsi         = snap.get("rsi", 0)

    if stage_score >= 80:
        bullets.append(f"⭐ نقاط الاختراق ممتازة ({stage_score:.0f}/100) — إشارة عالية الجودة")
    elif stage_score >= 60:
        bullets.append(f"✅ نقاط الاختراق جيدة ({stage_score:.0f}/100)")
    else:
        bullets.append(f"📊 نقاط الاختراق متوسطة ({stage_score:.0f}/100)")

    age_wks = vol_age / 5
    if age_wks <= 2:
        bullets.append(f"💹 حجم تداول طازج — الاختراق حدث منذ {age_wks:.1f} أسبوع فقط")
    elif age_wks <= 4:
        bullets.append(f"💹 حجم تداول حديث — {age_wks:.1f} أسبوع من الاختراق")
    else:
        bullets.append(f"⏳ حجم تداول قديم نسبياً — {age_wks:.1f} أسبوع من الاختراق")

    if vol_rvol >= 2.0:
        bullets.append(f"🔥 حجم استثنائي — {vol_rvol:.1f}x المعدل الطبيعي")
    elif vol_rvol >= 1.5:
        bullets.append(f"📈 حجم تداول قوي — {vol_rvol:.1f}x المعدل")

    if adx >= 30:
        bullets.append(f"📈 الاتجاه قوي جداً — ADX عند {adx:.0f}")
    elif adx >= 20:
        bullets.append(f"📈 الاتجاه إيجابي — ADX عند {adx:.0f}")

    if 50 <= rsi <= 70:
        bullets.append(f"⚡ الزخم في المنطقة المثالية — RSI عند {rsi:.0f}")
    elif rsi > 75:
        bullets.append(f"⚠️ مشتري بإفراط — RSI عند {rsi:.0f}، احتمال تصحيح")

    bullets.extend(_regime_bullet(regime))
    return bullets[:5]


# ── Trend ──────────────────────────────────────────────────────────────────────

def _explain_trend(snap: dict, regime: str) -> list[str]:
    bullets = []

    grade          = snap.get("grade", "A")
    trend_strength = snap.get("trend_strength", 0)
    adx            = snap.get("adx", 0)
    rsi            = snap.get("rsi", 0)

    if grade == "A+":
        bullets.append("⭐ إشارة A+ — أقوى درجات بداية الاتجاه الصاعد")
    else:
        bullets.append("✅ إشارة A — اتجاه صاعد مؤكد بعدة مؤشرات")

    if trend_strength >= 80:
        bullets.append(f"🚀 قوة الاتجاه ممتازة ({trend_strength:.0f}/100)")
    elif trend_strength >= 60:
        bullets.append(f"📈 قوة الاتجاه جيدة ({trend_strength:.0f}/100)")

    if adx >= 30:
        bullets.append(f"📈 ADX عند {adx:.0f} — زخم صاعد قوي ومستمر")
    elif adx >= 20:
        bullets.append(f"📈 ADX عند {adx:.0f} — تأكيد الاتجاه الصاعد")

    if 50 <= rsi <= 70:
        bullets.append(f"⚡ RSI عند {rsi:.0f} — الزخم في النطاق المثالي")
    elif rsi > 75:
        bullets.append(f"⚠️ RSI عند {rsi:.0f} — مشتري بإفراط، احذر")
    elif rsi < 50:
        bullets.append(f"📉 RSI عند {rsi:.0f} — الزخم ضعيف نسبياً")

    bullets.extend(_regime_bullet(regime))
    return bullets[:5]


# ── VOL Radar ──────────────────────────────────────────────────────────────────

def _explain_vol(snap: dict, regime: str) -> list[str]:
    bullets = []

    vol_rvol      = snap.get("vol_rvol", 0)
    vol_age       = snap.get("vol_age_bars", 0)
    ema_gap_pct   = snap.get("ema_gap_pct", 0)
    watch_reasons = snap.get("watch_reasons", [])

    bullets.append("👁️ إشارة مراقبة فقط — لا تشتري بعد، انتظر إشارة الاختراق")

    if vol_rvol >= 2.0:
        bullets.append(f"🔥 حجم استثنائي — {vol_rvol:.1f}x المعدل الطبيعي")
    elif vol_rvol >= 1.5:
        bullets.append(f"💹 حجم قوي — {vol_rvol:.1f}x المعدل")

    if ema_gap_pct <= 3:
        bullets.append(f"📊 السعر قريب جداً من المتوسطات — فجوة {ema_gap_pct:.1f}٪ فقط")
    elif ema_gap_pct <= 8:
        bullets.append(f"📊 السعر قريب من المتوسطات — فجوة {ema_gap_pct:.1f}٪")

    age_wks = vol_age / 5
    if age_wks <= 2:
        bullets.append(f"⏱️ الحجم طازج — منذ {age_wks:.1f} أسبوع فقط")

    if watch_reasons:
        bullets.append(f"📌 {watch_reasons[0]}")

    bullets.extend(_regime_bullet(regime))
    return bullets[:5]


# ── Shared ─────────────────────────────────────────────────────────────────────

def _regime_bullet(regime: str) -> list[str]:
    notes = {
        "BULL":          "🟢 السوق في مرحلة صعود — يدعم الفرص الطويلة",
        "BEAR":          "🔴 السوق في مرحلة هبوط — كن حذراً وخفف الأحجام",
        "VOLATILE":      "⚠️ السوق متقلب — استخدم وقف خسارة أوسع",
        "LOW_LIQUIDITY": "⚠️ سيولة منخفضة — احذر من الفجوات السعرية",
    }
    note = notes.get(regime)
    return [note] if note else []
