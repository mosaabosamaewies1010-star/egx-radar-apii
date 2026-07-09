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
    """Fetch OHLCV for a list of symbols. Returns {symbol: df | None}."""
    result: dict[str, Optional[pd.DataFrame]] = {}
    for sym in symbols:
        result[sym] = fetch_ohlcv(sym, period=period)
    return result


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
