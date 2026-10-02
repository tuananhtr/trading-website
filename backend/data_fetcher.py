"""
data_fetcher.py — Downloads OHLCV data using vnstock (Vietnam-specific).

Primary source  : TCBS (Techcombank Securities) — reliable, no auth needed
Fallback source : SSI  (SSI Securities)

vnstock 0.2.x is used — completely free, no rate limits.
Ticker format: plain symbol e.g. "HPG", "VNM" (no exchange suffix needed).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from database import get_ohlcv, get_last_stored_date, has_data, upsert_ohlcv

logger = logging.getLogger(__name__)

START_DATE = "2010-01-01"
SOURCES = ["TCBS", "SSI", "VND"]   # tried in order


# ---------------------------------------------------------------------------
# Internal download helper
# ---------------------------------------------------------------------------

def _download(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Download daily OHLCV from vnstock, trying each source in order.
    Returns a DataFrame with DatetimeIndex named 'date' and
    columns [open, high, low, close, volume].
    """
    from vnstock import stock_historical_data   # imported here to keep startup fast

    symbol = ticker.upper().replace(".VN", "")  # strip suffix if user passed one

    raw = pd.DataFrame()
    for source in SOURCES:
        try:
            raw = stock_historical_data(
                symbol=symbol,
                start_date=start,
                end_date=end,
                resolution="1D",
                type="stock",
                beautify=True,
                source=source,
            )
            if raw is not None and not raw.empty:
                logger.info(f"[{ticker}] Downloaded {len(raw)} rows from {source}")
                break
        except Exception as exc:
            logger.warning(f"[{ticker}] {source} failed: {exc}")
            raw = pd.DataFrame()

    if raw is None or raw.empty:
        logger.error(f"[{ticker}] All sources failed for {start} → {end}")
        return pd.DataFrame()

    # ── Normalise columns ──────────────────────────────────────────────────
    # vnstock beautify=True returns: time, open, high, low, close, volume
    raw.columns = [c.lower() for c in raw.columns]

    # Rename 'time' → 'date' if needed
    if "time" in raw.columns and "date" not in raw.columns:
        raw = raw.rename(columns={"time": "date"})

    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(raw.columns)
    if missing:
        logger.error(f"[{ticker}] Missing columns after normalise: {missing}")
        return pd.DataFrame()

    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.set_index("date")
    raw = raw[["open", "high", "low", "close", "volume"]].apply(
        pd.to_numeric, errors="coerce"
    )
    raw = raw.dropna(subset=["close"])
    raw = raw.sort_index()
    return raw


# ---------------------------------------------------------------------------
# Public API (same interface as before — main.py does not change)
# ---------------------------------------------------------------------------

def fetch_and_store(ticker: str) -> pd.DataFrame:
    """
    Full initial download: fetch from START_DATE to today and persist to DB.
    Called the first time a ticker is added to the watchlist.
    """
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
    """
    Fetch only missing days (last stored date → today) and append to DB.
    Called each time a ticker is loaded to keep data fresh.
    """
    ticker = ticker.upper().replace(".VN", "")

    last = get_last_stored_date(ticker)
    if last is None:
        return fetch_and_store(ticker)

    # Start from the day after last stored date
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
    """
    Main entry point used by API routes.
    Returns full OHLCV from DB, fetching/updating from vnstock if needed.
    """
    ticker = ticker.upper().replace(".VN", "")

    if not has_data(ticker):
        return fetch_and_store(ticker)

    return incremental_update(ticker)
