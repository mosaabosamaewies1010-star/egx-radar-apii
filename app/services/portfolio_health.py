"""
Portfolio Health Engine — approved logic (see EGX Radar research thread).

Health Score = التنويع (30) + المخاطرة (25) + الجودة الفنية (25) + الأداء (20)

كل مكوّن شفاف ومحسوب من بيانات حقيقية موجودة بالفعل — مفيش رقم مركّب غامض.
مبني على درس بحثي موثّق: أي رقم مركّب من غير تفصيل مكوّناته غير موثوق (Research
Journal, Chapter 4 — نفس السبب اللي خلّينا radar_score يبقى Explanation Layer).

مُتعمّد إنه بسيط: 4 مكوّنات بس، من بيانات موجودة فعلاً (قطاع، ATR%، radar_score،
ربح/خسارة) — بدون محاكاة "ماذا لو" وبدون مقارنة بمؤشر EGX30 (محتاجة بنية تتبّع
تاريخي لكل مركز مش متوفرة حاليًا، فمش هنّدعي دقة مش عندنا).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class PositionSnapshot:
    symbol:       str
    name_ar:      str
    sector:       str | None
    weight_pct:   float   # % من إجمالي رأس المال المستثمر (بالتكلفة)
    cost_basis:   float
    radar_score:  float | None
    atr_pct:      float | None


@dataclass
class HealthResult:
    health_score: float | None   # None لو مفيش مراكز مفتوحة
    components: dict = field(default_factory=dict)
    warnings:   list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    positions:  list[dict] = field(default_factory=list)
    message:    str | None = None   # لما health_score يبقى None


def _diversification_score(sector_weights: dict[str, float], n_positions: int) -> tuple[float, dict]:
    """30 نقطة — من تركيز القطاع الأعلى + عدد المراكز."""
    if not sector_weights:
        return 0.0, {}

    top_sector, top_pct = max(sector_weights.items(), key=lambda kv: kv[1])

    if top_pct <= 25:
        score = 30.0
    elif top_pct <= 40:
        score = 20.0
    elif top_pct <= 60:
        score = 10.0
    else:
        score = 0.0

    if n_positions < 3:
        score = max(0.0, score - 10.0)

    return score, {"top_sector": top_sector, "top_sector_pct": round(top_pct, 1)}


def _risk_score(weighted_atr_pct: float | None) -> float:
    """25 نقطة — من متوسط ATR% مرجّح بحجم المركز."""
    if weighted_atr_pct is None:
        return 12.5  # منتصف — بيانات ناقصة، مش نحكم بالسلب أو الإيجاب
    if weighted_atr_pct <= 1.5:
        return 25.0
    if weighted_atr_pct <= 3.0:
        return 18.0
    if weighted_atr_pct <= 5.0:
        return 10.0
    return 3.0


def _technical_quality_score(weighted_radar_score: float | None) -> float:
    """25 نقطة — من متوسط radar_score (0-100) مرجّح بحجم المركز."""
    if weighted_radar_score is None:
        return 12.5
    return round(weighted_radar_score / 100 * 25, 1)


def _performance_score(return_pct: float | None) -> float:
    """20 نقطة — من نسبة العائد الكلي (محقق + غير محقق) على رأس المال المستثمر."""
    if return_pct is None:
        return 10.0
    if return_pct >= 15:
        return 20.0
    if return_pct >= 5:
        return 15.0
    if return_pct >= 0:
        return 10.0
    if return_pct >= -10:
        return 5.0
    return 0.0


def compute_portfolio_health(
    open_holdings: list,          # PortfolioHolding objects (is_open=True)
    total_invested: float,
    total_unrealized_pnl: float | None,
    total_realized_pnl: float,
    latest_scores: dict[int, dict],   # stock_id -> {"score": float, "atr_pct": float} | {}
) -> HealthResult:
    if not open_holdings or total_invested <= 0:
        return HealthResult(
            health_score=None,
            message="مفيش مراكز مفتوحة حاليًا — أضف صفقة عشان نقدر نحسب صحة المحفظة",
        )

    sector_weights: dict[str, float] = {}
    positions: list[PositionSnapshot] = []
    weighted_atr_sum = 0.0
    weighted_score_sum = 0.0
    atr_weight_total = 0.0
    score_weight_total = 0.0

    for h in open_holdings:
        stock = h.stock
        weight_pct = (h.cost_basis / total_invested) * 100 if total_invested > 0 else 0.0
        sector = getattr(stock, "sector", None) or "غير مصنّف"
        sector_weights[sector] = sector_weights.get(sector, 0.0) + weight_pct

        sc = latest_scores.get(h.stock_id, {}) or {}
        score    = sc.get("score")
        atr_pct  = sc.get("atr_pct")

        if score is not None:
            weighted_score_sum += score * weight_pct
            score_weight_total += weight_pct
        if atr_pct is not None:
            weighted_atr_sum += atr_pct * weight_pct
            atr_weight_total += weight_pct

        positions.append(PositionSnapshot(
            symbol=stock.symbol if stock else "—",
            name_ar=stock.name_ar if stock else "—",
            sector=sector,
            weight_pct=round(weight_pct, 1),
            cost_basis=h.cost_basis,
            radar_score=score,
            atr_pct=atr_pct,
        ))

    weighted_atr   = (weighted_atr_sum / atr_weight_total) if atr_weight_total > 0 else None
    weighted_score = (weighted_score_sum / score_weight_total) if score_weight_total > 0 else None

    total_pnl    = (total_unrealized_pnl or 0.0) + total_realized_pnl
    return_pct   = (total_pnl / total_invested * 100) if total_invested > 0 else None

    div_score, div_meta = _diversification_score(sector_weights, len(open_holdings))
    risk_score          = _risk_score(weighted_atr)
    quality_score       = _technical_quality_score(weighted_score)
    perf_score          = _performance_score(return_pct)

    health = round(div_score + risk_score + quality_score + perf_score, 1)

    warnings: list[str] = []
    recommendations: list[str] = []

    top_sector = div_meta.get("top_sector")
    top_pct    = div_meta.get("top_sector_pct", 0.0)
    if top_pct > 60:
        warnings.append(f"⚠️ تركيز مرتفع جدًا في قطاع {top_sector} ({top_pct}%) — التوزيع القطاعي غير متوازن")
        recommendations.append(f"قلّل وزن قطاع {top_sector} أو أضف أسهم من قطاعات تانية لتوازن المحفظة")
    elif top_pct > 40:
        warnings.append(f"⚠️ تركيز ملحوظ في قطاع {top_sector} ({top_pct}%)")
        recommendations.append(f"فكّر تضيف تنويع أكتر برّه قطاع {top_sector}")

    if len(open_holdings) < 3:
        warnings.append(f"⚠️ عدد المراكز قليل ({len(open_holdings)}) — التنويع محدود بغض النظر عن القطاعات")
        recommendations.append("زوّد عدد المراكز المفتوحة (3 على الأقل) لتقليل مخاطرة التركّز")

    if weighted_atr is not None and weighted_atr > 4:
        warnings.append(f"⚠️ محفظتك متقلبة نسبيًا (متوسط ATR% مرجّح {weighted_atr:.1f}%) — مخاطرة سعرية عالية")
        recommendations.append("راجع أحجام المراكز في الأسهم عالية التقلب، أو استخدم وقف خسارة أضيق")

    if weighted_score is not None and weighted_score < 45:
        warnings.append(f"⚠️ متوسط الجودة الفنية لمراكزك منخفض ({weighted_score:.0f}/100)")
        recommendations.append("راجع الأسهم صاحبة أقل radar_score في محفظتك — ممكن يكونوا خرجوا من نطاق الاتجاه الصاعد")

    if return_pct is not None and return_pct < -10:
        warnings.append(f"⚠️ محفظتك في خسارة تراكمية ({return_pct:.1f}%)")
        recommendations.append("راجع المراكز الخاسرة بشكل فردي — قرار الاحتفاظ لازم يكون مبني على السهم نفسه مش الأمل بالتعافي")

    return HealthResult(
        health_score=health,
        components={
            "diversification": {"score": round(div_score, 1), "max": 30, **div_meta},
            "risk":             {"score": round(risk_score, 1), "max": 25,
                                  "weighted_atr_pct": round(weighted_atr, 2) if weighted_atr is not None else None},
            "technical_quality": {"score": round(quality_score, 1), "max": 25,
                                   "weighted_radar_score": round(weighted_score, 1) if weighted_score is not None else None},
            "performance":      {"score": round(perf_score, 1), "max": 20,
                                  "return_pct": round(return_pct, 2) if return_pct is not None else None},
        },
        warnings=warnings,
        recommendations=recommendations,
        positions=[
            {
                "symbol": p.symbol, "name_ar": p.name_ar, "sector": p.sector,
                "weight_pct": p.weight_pct, "cost_basis": round(p.cost_basis, 2),
                "radar_score": p.radar_score, "atr_pct": p.atr_pct,
            }
            for p in sorted(positions, key=lambda x: x.weight_pct, reverse=True)
        ],
    )
