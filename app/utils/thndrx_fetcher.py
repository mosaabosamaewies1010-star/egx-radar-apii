"""
thndrx_fetcher.py — Phase 3A
Data access layer: يقرأ OHLCV من thndrx_ohlcv عبر Supabase REST API (HTTPS).

نفس approach بتاع thndrx_uploader.py — مثبت على Windows وLinux.
لا يعتمد على psycopg2 مباشر (يفشل على Windows بسبب Supabase pooler tenant routing).

المتغيرات المطلوبة:
  SUPABASE_URL         — نفس المستخدم في الـuploader
  SUPABASE_SERVICE_KEY — نفس المستخدم في الـuploader

Engines لا تتأثر — التغيير الوحيد: مصدر OHLCV.
"""
import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_EGX_WEEKDAYS   = {0, 1, 2, 3, 6}  # Mon=0,Tue=1,Wed=2,Thu=3,Sun=6
_LOOKBACK_DAYS  = 180               # ≈ 125 EGX trading days → يغطي EMA50 + VOL_LOOKBACK=60
_SCAN_START_HOUR = 15
_PAGE_SIZE      = 1000              # Supabase REST API max rows per request
_sb_client      = None


def _get_client():
    global _sb_client
    if _sb_client is None:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL or SUPABASE_SERVICE_KEY not set — "
                "add them to Render environment variables"
            )
        _sb_client = create_client(url, key)
    return _sb_client


def _expected_session() -> date:
    """Returns the EGX session date we expect ThndrX data for right now."""
    import pytz
    cairo = pytz.timezone("Africa/Cairo")
    now   = datetime.now(cairo)
    today = now.date()
    if today.weekday() in _EGX_WEEKDAYS and now.hour >= _SCAN_START_HOUR:
        return today
    check = today - timedelta(days=1)
    for _ in range(7):
        if check.weekday() in _EGX_WEEKDAYS:
            return check
        check -= timedelta(days=1)
    return today


def _rows_to_df(rows: list[dict]) -> Optional[pd.DataFrame]:
    """
    Supabase REST response rows → standard OHLCV DataFrame.
    Index = DatetimeIndex (day), columns = open/high/low/close/volume.
    """
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["day"] = pd.to_datetime(df["day"])
    df = df.set_index("day").sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "volume"])
    return df if not df.empty else None


# ── Public API ────────────────────────────────────────────────────────────────

def check_thndrx_freshness() -> tuple[bool, str]:
    """
    يتحقق من thndrx_freshness:
    - يحسب الـsession المتوقعة بناءً على وقت Cairo الحالي
    - لو مفيش record → (False, msg) → SCAN BLOCKED
    - لو موجود → (True, msg) → OK
    """
    expected = _expected_session()
    try:
        sb = _get_client()
        res = sb.table("thndrx_freshness") \
                .select("session_date,symbol_count,row_count") \
                .eq("session_date", str(expected)) \
                .limit(1) \
                .execute()
    except Exception as exc:
        return False, f"thndrx_freshness: error — {exc}"

    if not res.data:
        return False, (
            f"thndrx_freshness: NO record for session={expected} — "
            f"run thndrx_uploader.py first"
        )
    r = res.data[0]
    return True, (
        f"thndrx_freshness: OK session={r['session_date']} "
        f"symbols={r['symbol_count']} rows={r['row_count']}"
    )


def fetch_thndrx_ohlcv(symbol: str) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV for ONE symbol from thndrx_ohlcv.
    Same return contract as data_fetcher.fetch_ohlcv():
      DatetimeIndex + columns: open/high/low/close/volume
    """
    start = str(date.today() - timedelta(days=_LOOKBACK_DAYS))
    # _LOOKBACK_DAYS=180 calendar days ≈ 125 EGX trading days — well under 1000.
    # Explicit limit avoids relying on Supabase PostgREST default max_rows.
    _SINGLE_SYM_LIMIT = _LOOKBACK_DAYS + 50   # 230 → safe ceiling for any 180-day window
    try:
        sb   = _get_client()
        rows = sb.table("thndrx_ohlcv") \
                 .select("day,open,high,low,close,volume") \
                 .eq("symbol", symbol) \
                 .gte("day", start) \
                 .order("day") \
                 .limit(_SINGLE_SYM_LIMIT) \
                 .execute() \
                 .data
    except Exception as exc:
        logger.error("thndrx_fetcher.fetch_ohlcv(%s): %s", symbol, exc)
        return None

    if not rows:
        logger.debug("thndrx_fetcher: no data for %s", symbol)
        return None

    df = _rows_to_df(rows)
    if df is None or len(df) < 20:
        logger.warning("thndrx_fetcher: insufficient rows for %s (%d)", symbol, len(rows))
        return None
    return df


def fetch_thndrx_multiple(symbols: list[str]) -> dict[str, Optional[pd.DataFrame]]:
    """
    Bulk-fetch OHLCV for all symbols via paginated Supabase REST calls.
    Returns {symbol: DataFrame | None} — same contract as fetch_multiple().

    Strategy:
    - فلتر by date فقط + paginate بـ1000 row/request
    - تجميع rows per symbol في Python
    - عدد الـrequests ≈ 34 لـ~33K rows (267 symbols × 125 EGX days)
    """
    if not symbols:
        return {}

    start    = str(date.today() - timedelta(days=_LOOKBACK_DAYS))
    sym_set  = set(symbols)
    all_rows: list[dict] = []
    page     = 0

    try:
        sb = _get_client()
        while True:
            res = sb.table("thndrx_ohlcv") \
                    .select("symbol,day,open,high,low,close,volume") \
                    .gte("day", start) \
                    .order("symbol") \
                    .order("day") \
                    .range(page * _PAGE_SIZE, (page + 1) * _PAGE_SIZE - 1) \
                    .execute()
            if not res.data:
                break
            all_rows.extend(res.data)
            if len(res.data) < _PAGE_SIZE:
                break
            page += 1
    except Exception as exc:
        logger.error("thndrx_fetcher.fetch_multiple: %s", exc)
        return {sym: None for sym in symbols}

    # Group by symbol
    by_sym: dict[str, list[dict]] = {}
    for row in all_rows:
        sym = row["symbol"]
        if sym not in sym_set:
            continue
        if sym not in by_sym:
            by_sym[sym] = []
        by_sym[sym].append({k: row[k] for k in ("day", "open", "high", "low", "close", "volume")})

    result: dict[str, Optional[pd.DataFrame]] = {}
    for sym in symbols:
        raw = by_sym.get(sym)
        df  = _rows_to_df(raw) if raw else None
        # Mirror data_fetcher.fetch_multiple behaviour: < 20 bars → None
        # (thin/newly-listed symbols are skipped by engines exactly as before)
        if df is not None and len(df) < 20:
            logger.debug("thndrx_fetcher: thin symbol %s (%d bars) → None", sym, len(df))
            df = None
        result[sym] = df

    found = sum(1 for v in result.values() if v is not None)
    logger.info(
        "thndrx_fetcher: %d/%d symbols fetched (%d rows, %d pages, from %s)",
        found, len(symbols), len(all_rows), page + 1, start,
    )
    return result
