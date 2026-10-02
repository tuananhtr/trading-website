"""
data_fetcher.py — Downloads OHLCV data using yfinance.

Vietnam stocks use the .VN suffix on Yahoo Finance (e.g. HPG.VN, VNM.VN).
Data is downloaded once and stored in the local DB; subsequent calls
only fetch missing days (incremental updates).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from database import get_ohlcv, get_last_stored_date, has_data, upsert_ohlcv

logger = logging.getLogger(__name__)

START_DATE = "2010-01-01"


def _yf_ticker(ticker: str) -> str:
    """Ensure ticker has .VN suffix for Yahoo Finance."""
    t = ticker.upper().replace(".VN", "")
    return f"{t}.VN"


def _download(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Download daily OHLCV from Yahoo Finance.
    Returns a DataFrame with DatetimeIndex named 'date' and
    columns [open, high, low, close, volume].
    """
    yf_sym = _yf_ticker(ticker)
    try:
        raw = yf.download(
            yf_sym,
            start=start,
            end=end,
            interval="1d",
            auto_adjust=True,
            progress=False,
            multi_level_index=False,
        )
    except TypeError:
        # Older yfinance versions use multi_level_column
        raw = yf.download(
            yf_sym,
            start=start,
            end=end,
            interval="1d",
            auto_adjust=True,
            progress=False,
        )

    if raw is None or raw.empty:
        logger.error(f"[{ticker}] yfinance returned no data for {start} → {end}")
        return pd.DataFrame()

    # Normalise columns
    raw.columns = [c.lower() for c in raw.columns]
    raw.index.name = "date"

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(raw.columns)
    if missing:
        logger.error(f"[{ticker}] Missing columns: {missing}")
        return pd.DataFrame()

    df = raw[["open", "high", "low", "close", "volume"]].copy()
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=["close"])
    df = df.sort_index()
    logger.info(f"[{ticker}] Downloaded {len(df)} rows from yfinance")
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_and_store(ticker: str) -> pd.DataFrame:
    """Full initial download from START_DATE to today."""
    ticker = ticker.upper().replace(".VN", "")
    logger.info(f"[{ticker}] Full download from {START_DATE}…")

    today = date.today().strftime("%Y-%m-%d")
    df = _download(ticker, START_DATE, today)

    if df.empty:
        logger.warning(f"[{ticker}] No data returned — skipping DB write")
        return df

    rows = upsert_ohlcv(df, ticker)
    logger.info(f"[{ticker}] Stored {rows} rows in DB")
    return df


def incremental_update(ticker: str) -> pd.DataFrame:
    """Fetch only missing days and append to DB."""
    ticker = ticker.upper().replace(".VN", "")

    last = get_last_stored_date(ticker)
    if last is None:
        return fetch_and_store(ticker)

    start = (last + timedelta(days=1)).strftime("%Y-%m-%d")
    today = date.today().strftime("%Y-%m-%d")

    if start > today:
        logger.info(f"[{ticker}] Already up-to-date (last: {last})")
        return get_ohlcv(ticker)

    logger.info(f"[{ticker}] Incremental update {start} → {today}")
    new_data = _download(ticker, start, today)

    if not new_data.empty:
        rows = upsert_ohlcv(new_data, ticker)
        logger.info(f"[{ticker}] Appended {rows} new rows")

    return get_ohlcv(ticker)


def get_or_fetch(ticker: str) -> pd.DataFrame:
    """Main entry point — returns full OHLCV, fetching/updating as needed."""
    ticker = ticker.upper().replace(".VN", "")

    if not has_data(ticker):
        return fetch_and_store(ticker)

    return incremental_update(ticker)
