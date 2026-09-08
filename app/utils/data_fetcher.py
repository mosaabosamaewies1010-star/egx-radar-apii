"""
yfinance wrapper for Egyptian stocks (.CA suffix).
All EGX symbols are fetched as SYMBOL.CA
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# EGX trading hours: 10:00–14:30 CLT (GMT+2)
EGX_SUFFIX = ".CA"
MIN_ADT_EGP = 3_000_000   # 3M EGP — below this, stock is excluded from scoring


def egx_ticker(symbol: str) -> str:
    """Convert bare symbol to yfinance format: COMI → COMI.CA"""
    symbol = symbol.upper().strip()
    return symbol if symbol.endswith(EGX_SUFFIX) else symbol + EGX_SUFFIX


def fetch_ohlcv(symbol: str, period: str = "3mo") -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV data for an EGX stock.
    Returns None on failure (caller handles fallback).
    """
    ticker = egx_ticker(symbol)
    try:
        df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if df is None or df.empty:
            logger.warning("No data for %s", ticker)
            return None

        # Flatten multi-level columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        df = df.rename(columns=str.lower)
        df.index = pd.to_datetime(df.index)
        df = df.dropna(subset=["close", "volume"])

        if len(df) < 20:
            logger.warning("Insufficient data for %s (%d rows)", ticker, len(df))
            return None

        return df

    except Exception as exc:
        logger.error("yfinance error for %s: %s", ticker, exc)
        return None


def fetch_multiple(symbols: list[str], period: str = "3mo") -> dict[str, Optional[pd.DataFrame]]:
    """
    Fetch OHLCV for all symbols in one batched yfinance call.
    Single API call avoids per-ticker rate-limiting on Render's shared IP.
    Falls back to per-symbol calls if the batch fails or returns <50% coverage.
    """
    result: dict[str, Optional[pd.DataFrame]] = {s: None for s in symbols}
    if not symbols:
        return result

    tickers = [egx_ticker(s) for s in symbols]
    ticker_to_sym = {egx_ticker(s): s for s in symbols}

    try:
        raw = yf.download(
            tickers, period=period, auto_adjust=True,
            progress=False, group_by="ticker", threads=True,
        )
        if raw is None or raw.empty:
            raise ValueError("batch returned empty")

        for ticker, sym in ticker_to_sym.items():
            try:
                # group_by="ticker" → MultiIndex with ticker at level 0
                if isinstance(raw.columns, pd.MultiIndex):
                    if ticker not in raw.columns.get_level_values(0):
                        continue
                    df = raw[ticker].copy()
                else:
                    df = raw.copy()

                df.columns = [c.lower() for c in df.columns]
                df.index = pd.to_datetime(df.index)
                df = df.dropna(subset=["close", "volume"])
                if len(df) >= 20:
                    result[sym] = df
                else:
                    logger.warning("Batch: insufficient rows for %s (%d)", ticker, len(df))
            except Exception as _pe:
                logger.warning("Batch: parse error for %s: %s", ticker, _pe)

        success_n = sum(1 for v in result.values() if v is not None)
        logger.info("fetch_multiple: batch → %d/%d symbols", success_n, len(symbols))

        if success_n < len(symbols) * 0.5:
            logger.warning("fetch_multiple: batch coverage low (%d/%d) — falling back per-symbol",
                           success_n, len(symbols))
            raise ValueError("low coverage")

        return result

    except Exception as _be:
        logger.warning("fetch_multiple: batch failed (%s) — falling back per-symbol", _be)
        for sym in symbols:
            result[sym] = fetch_ohlcv(sym, period=period)
        return result


def fetch_fundamentals(symbol: str) -> dict:
    """
    Best-effort fundamentals snapshot from yfinance's Ticker.info.
    Coverage for EGX stocks is inconsistent — many fields (dividend for
    non-payers, EPS for some small caps) legitimately come back None.
    Caller must treat every value as optional; never fabricate a fallback.
    """
    ticker = egx_ticker(symbol)
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:
        logger.warning("yfinance fundamentals error for %s: %s", ticker, exc)
        return {}

    div_yield = info.get("trailingAnnualDividendYield")
    return {
        "market_cap":     info.get("marketCap"),
        "pe_ratio":       info.get("trailingPE"),
        "eps":            info.get("epsTrailingTwelveMonths"),
        "dividend_yield": round(div_yield * 100, 2) if div_yield is not None else None,
        "week52_high":    info.get("fiftyTwoWeekHigh"),
        "week52_low":     info.get("fiftyTwoWeekLow"),
        "book_value":     info.get("bookValue"),
    }


def compute_adt(df: pd.DataFrame, window: int = 20) -> float:
    """Average Daily Turnover in EGP over last `window` days."""
    if df is None or df.empty:
        return 0.0
    turnover = (df["close"] * df["volume"]).tail(window)
    return float(turnover.mean()) if not turnover.empty else 0.0


def assess_data_quality(df: Optional[pd.DataFrame], symbol: str) -> str:
    """
    Returns: HIGH | MEDIUM | LOW | NO_DATA
    Based on: data availability, recency, NaN gaps.
    """
    if df is None or df.empty:
        return "NO_DATA"

    last_date = df.index[-1].date()
    days_old  = (datetime.now().date() - last_date).days

    nan_pct   = df[["open", "high", "low", "close", "volume"]].isna().mean().mean()
    rows      = len(df)

    if days_old > 5:
        return "LOW"
    if nan_pct > 0.05 or rows < 30:
        return "MEDIUM"
    if days_old > 2:
        return "MEDIUM"
    return "HIGH"
