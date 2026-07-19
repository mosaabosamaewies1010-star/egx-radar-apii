"""
Telegram bot webhook — EGX Radar

User commands:
  /start         — ترحيب + قائمة الأوامر
  /سهم COMI      — تحليل سهم
  /اشارات        — إشارات SRA اليوم
  /سوق           — حالة السوق
  /مفتوحة        — الصفقات المفتوحة
  /مساعدة        — قائمة الأوامر

Admin commands (TELEGRAM_CHAT_ID only):
  /صحة           — ملخص صحة النظام (نفس منطق بطاقات الأدمن)
  /مربحة         — آخر 5 صفقات رابحة
  /خاسرة         — آخر 5 صفقات خاسرة
"""
import os
import logging
import requests
from datetime import date

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)
telegram_bp = Blueprint("telegram", __name__)

BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")


# ── Low-level sender ──────────────────────────────────────────────────────────

def send_message(chat_id: str | int, text: str, parse_mode: str = "HTML") -> None:
    """Send a message via Telegram Bot API. Silently ignores failures."""
    if not BOT_TOKEN:
        logger.warning("TELEGRAM_TOKEN not set — skipping send")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
    except Exception:
        logger.exception("Telegram send failed (chat_id=%s)", chat_id)


def _is_admin(chat_id) -> bool:
    return str(chat_id) == str(ADMIN_CHAT)


# ── Command handlers ──────────────────────────────────────────────────────────

def _cmd_start(chat_id):
    send_message(chat_id, (
        "مرحباً بك في <b>EGX Radar</b> 📡\n\n"
        "أنا بوت تحليل البورصة المصرية — الأوامر المتاحة:\n\n"
        "📊 /سهم [الرمز] — تحليل سهم (مثال: /سهم COMI)\n"
        "🎯 /اشارات — إشارات SRA لليوم\n"
        "🌍 /سوق — حالة السوق الحالية\n"
        "📈 /مفتوحة — الصفقات المفتوحة\n"
        "❓ /مساعدة — هذه القائمة"
    ))


def _cmd_help(chat_id):
    send_message(chat_id, (
        "📋 <b>أوامر EGX Radar</b>\n\n"
        "/سهم [الرمز] — تحليل سهم (مثال: /سهم COMI)\n"
        "/اشارات — إشارات SRA اليوم\n"
        "/سوق — حالة السوق الحالية\n"
        "/مفتوحة — الصفقات المفتوحة حالياً\n"
        "/مساعدة — هذه القائمة"
    ))


def _cmd_stock(chat_id, symbol: str):
    from app.models.stock import Stock
    from app.models.score import RadarScoreHistory
    from app.models.opportunity import Opportunity

    symbol = symbol.upper().strip()
    if not symbol:
        send_message(chat_id, "❌ الرجاء إدخال رمز السهم\nمثال: /سهم COMI")
        return

    stock = Stock.query.filter_by(symbol=symbol).first()
    if not stock:
        send_message(chat_id, f"❌ السهم <b>{symbol}</b> غير موجود في القاعدة")
        return

    today = date.today()

    score_rec = (
        RadarScoreHistory.query
        .filter_by(stock_id=stock.id)
        .order_by(RadarScoreHistory.run_date.desc())
        .first()
    )

    opp = (
        Opportunity.query
        .filter(
            Opportunity.stock_id == stock.id,
            Opportunity.outcome == "PENDING",
            Opportunity.is_active.is_(True),
            ~Opportunity.opp_type.like("TREND_%"),
        )
        .order_by(Opportunity.run_date.desc())
        .first()
    )

    lines = [f"📌 <b>{stock.name_ar}</b> ({symbol})"]
    if stock.sector:
        lines.append(f"القطاع: {stock.sector}")

    if stock.last_price:
        lines.append(f"💰 السعر: <b>{stock.last_price:.2f} ج</b>")

    if score_rec:
        score = round(score_rec.score, 1)
        age   = (today - score_rec.run_date).days if score_rec.run_date else "?"
        emoji = "🔥" if score >= 70 else "📊" if score >= 50 else "📉"
        lines.append(f"{emoji} Radar Score: <b>{score}/100</b> (منذ {age} يوم)")
    else:
        lines.append("📊 Radar Score: لا يوجد تقييم بعد")

    if opp:
        snap  = opp.feature_snapshot or {}
        grade = snap.get("sra_grade", "")
        rr    = f" | RR {opp.rr_ratio:.1f}" if opp.rr_ratio else ""
        lines.append(
            f"\n🎯 <b>إشارة مفتوحة [{grade}]</b>\n"
            f"دخول: {opp.entry_price:.2f} | TP: {opp.tp1_price:.2f} | SL: {opp.sl_price:.2f}{rr}"
        )

    send_message(chat_id, "\n".join(lines))


def _cmd_signals(chat_id):
    from app.models.opportunity import Opportunity

    today = date.today()
    rows = (
        Opportunity.query
        .filter(
            Opportunity.run_date == today,
            ~Opportunity.opp_type.like("TREND_%"),
        )
        .order_by(Opportunity.radar_score.desc())
        .limit(5)
        .all()
    )

    if not rows:
        send_message(chat_id, f"📭 لا توجد إشارات SRA اليوم ({today.strftime('%Y-%m-%d')})")
        return

    lines = [f"🎯 <b>إشارات SRA اليوم</b> — {today.strftime('%Y-%m-%d')}\n"]
    for o in rows:
        sym   = o.stock.symbol  if o.stock else "?"
        name  = o.stock.name_ar if o.stock else "?"
        snap  = o.feature_snapshot or {}
        grade = snap.get("sra_grade", "")
        rr    = f" | RR {o.rr_ratio:.1f}" if o.rr_ratio else ""
        lines.append(
            f"• <b>{sym}</b> {name} [{grade}]\n"
            f"  دخول {o.entry_price:.2f} | TP {o.tp1_price:.2f} | SL {o.sl_price:.2f}{rr}"
        )

    send_message(chat_id, "\n".join(lines))


def _cmd_market(chat_id):
    from app.models.regime import MarketRegimeHistory

    rec = MarketRegimeHistory.query.order_by(MarketRegimeHistory.run_date.desc()).first()
    if not rec:
        send_message(chat_id, "⚠️ لا توجد بيانات عن حالة السوق حتى الآن")
        return

    emoji_map = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "🟡", "CAUTION": "⚠️"}
    emoji = emoji_map.get(rec.regime or "", "🌍")
    conf  = f"{rec.confidence:.0f}%" if rec.confidence else "N/A"
    dt    = rec.run_date.strftime("%Y-%m-%d") if rec.run_date else "N/A"

    send_message(chat_id, (
        f"🌍 <b>حالة السوق</b>\n\n"
        f"الحالة: {emoji} <b>{rec.regime}</b>\n"
        f"الثقة: {conf}\n"
        f"التاريخ: {dt}"
    ))


def _cmd_open(chat_id):
    from app.models.opportunity import Opportunity

    rows = (
        Opportunity.query
        .filter(
            Opportunity.opp_type.like("SRA_%"),
            Opportunity.outcome == "PENDING",
            Opportunity.is_active.is_(True),
        )
        .order_by(Opportunity.radar_score.desc())
        .limit(10)
        .all()
    )

    if not rows:
        send_message(chat_id, "📭 لا توجد صفقات SRA مفتوحة حالياً")
        return

    today = date.today()
    lines = [f"📈 <b>الصفقات المفتوحة ({len(rows)})</b>\n"]
    for o in rows:
        sym   = o.stock.symbol  if o.stock else "?"
        snap  = o.feature_snapshot or {}
        grade = snap.get("sra_grade", "")
        age   = (today - o.run_date).days if o.run_date else "?"
        lines.append(
            f"• <b>{sym}</b> [{grade}] منذ {age} يوم\n"
            f"  دخول {o.entry_price:.2f} | TP {o.tp1_price:.2f} | SL {o.sl_price:.2f}"
        )

    send_message(chat_id, "\n".join(lines))


# ── Admin commands (use same data as admin dashboard cards) ───────────────────

def _cmd_health(chat_id):
    from app.models.opportunity import Opportunity
    from app.models.score import RadarScoreHistory
    from app.models.regime import MarketRegimeHistory
    from app.models.user import User

    today = date.today()

    signals_today = Opportunity.query.filter_by(run_date=today).count()
    sra_open = Opportunity.query.filter(
        Opportunity.opp_type.like("SRA_%"),
        Opportunity.outcome == "PENDING",
        Opportunity.is_active.is_(True),
    ).count()

    closed   = Opportunity.query.filter(Opportunity.outcome.in_(["WIN", "LOSS"])).all()
    wins     = sum(1 for o in closed if o.outcome == "WIN")
    losses   = sum(1 for o in closed if o.outcome == "LOSS")
    decided  = wins + losses
    win_rate = f"{wins / decided * 100:.1f}%" if decided > 0 else "N/A"

    kb_size = Opportunity.query.filter(
        Opportunity.opp_type.like("SRA_%"),
        Opportunity.outcome.in_(["WIN", "LOSS"]),
    ).count()

    scored_today = RadarScoreHistory.query.filter_by(run_date=today).count()

    regime_rec = MarketRegimeHistory.query.order_by(MarketRegimeHistory.run_date.desc()).first()
    regime_str = regime_rec.regime if regime_rec else "N/A"

    total_users = User.query.count()
    pro_users   = User.query.filter_by(is_pro=True).count()

    send_message(chat_id, (
        f"🔧 <b>صحة النظام</b> — {today}\n\n"
        f"📊 أسهم فُحصت اليوم: <b>{scored_today}</b>\n"
        f"🎯 إشارات اليوم: <b>{signals_today}</b>\n"
        f"📈 SRA مفتوحة: <b>{sra_open}</b>\n"
        f"✅ رابحة: <b>{wins}</b> | ❌ خاسرة: <b>{losses}</b>\n"
        f"🏆 معدل الفوز: <b>{win_rate}</b>\n"
        f"📚 Knowledge Base: <b>{kb_size}</b> صفقة\n"
        f"🌍 السوق: <b>{regime_str}</b>\n"
        f"👥 المستخدمون: <b>{total_users}</b> (PRO: {pro_users})"
    ))


def _cmd_wins(chat_id):
    from app.models.opportunity import Opportunity

    rows = (
        Opportunity.query
        .filter_by(outcome="WIN")
        .order_by(Opportunity.closed_at.desc())
        .limit(5)
        .all()
    )
    if not rows:
        send_message(chat_id, "📭 لا توجد صفقات رابحة بعد")
        return

    lines = ["✅ <b>آخر الصفقات الرابحة</b>\n"]
    for o in rows:
        sym  = o.stock.symbol if o.stock else "?"
        pnl  = f"{o.pnl_pct:+.1f}%" if o.pnl_pct is not None else "N/A"
        days = o.hold_days or "?"
        lines.append(f"• <b>{sym}</b> | ربح: {pnl} | {days} يوم")

    send_message(chat_id, "\n".join(lines))


def _cmd_losses(chat_id):
    from app.models.opportunity import Opportunity

    rows = (
        Opportunity.query
        .filter_by(outcome="LOSS")
        .order_by(Opportunity.closed_at.desc())
        .limit(5)
        .all()
    )
    if not rows:
        send_message(chat_id, "📭 لا توجد صفقات خاسرة")
        return

    lines = ["❌ <b>آخر الصفقات الخاسرة</b>\n"]
    for o in rows:
        sym  = o.stock.symbol if o.stock else "?"
        pnl  = f"{o.pnl_pct:+.1f}%" if o.pnl_pct is not None else "N/A"
        days = o.hold_days or "?"
        lines.append(f"• <b>{sym}</b> | خسارة: {pnl} | {days} يوم")

    send_message(chat_id, "\n".join(lines))


# ── Message router ────────────────────────────────────────────────────────────

def _route(chat_id, text: str):
    t   = (text or "").strip()
    low = t.lower()

    if low.startswith("/start"):
        _cmd_start(chat_id)
    elif low.startswith("/مساعدة") or low.startswith("/help"):
        _cmd_help(chat_id)
    elif low.startswith("/سهم") or low.startswith("/stock"):
        parts  = t.split(maxsplit=1)
        symbol = parts[1].strip() if len(parts) > 1 else ""
        _cmd_stock(chat_id, symbol)
    elif low.startswith("/اشارات") or low.startswith("/signals"):
        _cmd_signals(chat_id)
    elif low.startswith("/سوق") or low.startswith("/market"):
        _cmd_market(chat_id)
    elif low.startswith("/مفتوحة") or low.startswith("/open"):
        _cmd_open(chat_id)
    elif low.startswith("/صحة") or low.startswith("/healthcheck"):
        if _is_admin(chat_id):
            _cmd_health(chat_id)
        else:
            send_message(chat_id, "🔒 هذا الأمر للمشرف فقط")
    elif low.startswith("/مربحة") or low.startswith("/wins"):
        if _is_admin(chat_id):
            _cmd_wins(chat_id)
        else:
            send_message(chat_id, "🔒 هذا الأمر للمشرف فقط")
    elif low.startswith("/خاسرة") or low.startswith("/losses"):
        if _is_admin(chat_id):
            _cmd_losses(chat_id)
        else:
            send_message(chat_id, "🔒 هذا الأمر للمشرف فقط")
    elif t.startswith("/"):
        send_message(chat_id, "❓ أمر غير معروف\nأرسل /مساعدة لقائمة الأوامر")


# ── Webhook endpoint ──────────────────────────────────────────────────────────

@telegram_bp.post("/api/telegram/webhook")
def webhook():
    data = request.get_json(silent=True) or {}
    msg  = data.get("message") or data.get("edited_message")
    if not msg:
        return jsonify({"ok": True})

    chat_id = msg.get("chat", {}).get("id")
    text    = msg.get("text", "")
    if not chat_id or not text:
        return jsonify({"ok": True})

    try:
        _route(chat_id, text)
    except Exception:
        logger.exception("telegram webhook: error handling update")
        send_message(chat_id, "⚠️ حدث خطأ داخلي، يرجى المحاولة لاحقاً")

    return jsonify({"ok": True})


# ── One-time webhook registration ─────────────────────────────────────────────

@telegram_bp.post("/api/telegram/register-webhook")
def register_webhook():
    """Call once to tell Telegram where to send updates."""
    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if api_key != os.getenv("BOT_API_KEY"):
        return jsonify({"error": "unauthorized"}), 401

    host = request.host_url.rstrip("/")
    url  = f"{host}/api/telegram/webhook"
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
        json={"url": url, "allowed_updates": ["message"]},
        timeout=10,
    )
    return jsonify(resp.json()), resp.status_code
