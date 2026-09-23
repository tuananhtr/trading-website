"""
data_fetcher.py - Downloads OHLCV data from yfinance and stores in SQLite.
Vietnam stocks traded on HOSE/HNX use the .VN suffix in yfinance.
"""
import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from database import get_last_stored_date, has_data, upsert_ohlcv

logger = logging.getLogger(__name__)

VN_START_DATE = "2010-01-01"


def _yf_ticker(ticker: str) -> str:
    """Normalise ticker: append .VN if not already present."""
    ticker = ticker.strip().upper()
    if not ticker.endswith(".VN"):
        ticker = ticker + ".VN"
    return ticker


def _download(yf_ticker: str, start: str, end: Optional[str] = None) -> pd.DataFrame:
    """Raw download from yfinance, returns clean DataFrame."""
    try:
        raw = yf.download(
            yf_ticker,
            start=start,
            end=end,
            progress=False,
            auto_adjust=True,
            multi_level_index=False,
        )
    except Exception as e:
        logger.error(f"yfinance download error for {yf_ticker}: {e}")
        return pd.DataFrame()

    if raw is None or raw.empty:
        logger.warning(f"No data returned from yfinance for {yf_ticker}")
        return pd.DataFrame()

    raw = raw.reset_index()

    # Normalise column names (yfinance sometimes returns MultiIndex)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw.columns = [c.lower() for c in raw.columns]

    # Keep only OHLCV columns
    needed = {"date", "open", "high", "low", "close", "volume"}
    # yfinance may use 'datetime' as the date column name
    if "datetime" in raw.columns:
        raw = raw.rename(columns={"datetime": "date"})
    missing = needed - set(raw.columns)
    if missing:
        logger.error(f"Missing columns {missing} for {yf_ticker}")
        return pd.DataFrame()

    df = raw[list(needed)].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    df = df.sort_values("date").reset_index(drop=True)
    return df


def fetch_and_store(ticker: str, force: bool = False) -> dict:
    """
    Full fetch: downloads from VN_START_DATE (2010) to today.
    If data already exists and force=False, does an incremental update instead.
    Returns dict with status and row count.
    """
    yf_t = _yf_ticker(ticker)

    if not force and has_data(ticker):
        return incremental_update(ticker)

    logger.info(f"Full fetch for {ticker} ({yf_t}) from {VN_START_DATE}")
    df = _download(yf_t, start=VN_START_DATE)
    if df.empty:
        return {"status": "error", "message": f"No data found for {ticker}", "rows": 0}

    rows = upsert_ohlcv(df, ticker)
    logger.info(f"Stored {rows} rows for {ticker}")
    return {"status": "ok", "rows": rows, "ticker": ticker}


def incremental_update(ticker: str) -> dict:
    """Download only missing dates (from last stored date to today)."""
    yf_t = _yf_ticker(ticker)
    last = get_last_stored_date(ticker)

    if last is None:
        return fetch_and_store(ticker, force=True)

    start = (last + timedelta(days=1)).strftime("%Y-%m-%d")
    today = date.today().strftime("%Y-%m-%d")

    if start > today:
        return {"status": "ok", "rows": 0, "message": "Already up to date", "ticker": ticker}

    logger.info(f"Incremental update for {ticker}: {start} → {today}")
    df = _download(yf_t, start=start)
    if df.empty:
        return {"status": "ok", "rows": 0, "message": "No new data", "ticker": ticker}

    rows = upsert_ohlcv(df, ticker)
    return {"status": "ok", "rows": rows, "ticker": ticker}


def get_or_fetch(ticker: str) -> pd.DataFrame:
    """
    Returns the full stored OHLCV DataFrame, fetching from yfinance if needed.
    Always does an incremental update to make sure data is current.
    """
    from database import get_ohlcv

    # If no data at all, do full fetch first
    if not has_data(ticker):
        result = fetch_and_store(ticker)
        if result["status"] == "error":
            return pd.DataFrame()
    else:
        # Always try an incremental update
        incremental_update(ticker)

    return get_ohlcv(ticker)
