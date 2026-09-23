"""
strategy.py - Technical indicator computation and buy signal detection.
Uses pure pandas/numpy — no pandas-ta dependency required.

Strategy (Long-term Reversal):
  BUY when ALL conditions are met on the same bar:
    1. Close < MA200  (price is below long-term trend — potential deep dip)
    2. RSI(14) < 30   (oversold)
    3. MACD(12,26,9) line crosses ABOVE signal line on this bar
       (momentum turning positive — confirmation)
"""
from __future__ import annotations

import logging
from typing import Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Strategy parameters
MA_PERIOD    = 200
RSI_PERIOD   = 14
MACD_FAST    = 12
MACD_SLOW    = 26
MACD_SIGNAL  = 9


# ─── Pure-pandas indicator helpers ───────────────────────────────────────────

def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ─── Main compute function ────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add technical indicator columns to *df*.

    Input:  DataFrame with columns [open, high, low, close, volume], DatetimeIndex.
    Output: Same df with extra columns:
            ma200, rsi, macd, macd_signal, macd_hist, buy_signal
    """
    if df.empty or len(df) < MA_PERIOD:
        df = df.copy()
        df["ma200"]       = np.nan
        df["rsi"]         = np.nan
        df["macd"]        = np.nan
        df["macd_signal"] = np.nan
        df["macd_hist"]   = np.nan
        df["buy_signal"]  = False
        return df

    df = df.copy()
    close = df["close"]

    df["ma200"]                          = _sma(close, MA_PERIOD)
    df["rsi"]                            = _rsi(close, RSI_PERIOD)
    df["macd"], df["macd_signal"], df["macd_hist"] = _macd(close, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    df["buy_signal"]                     = _detect_buy_signals(df)

    return df


def _detect_buy_signals(df: pd.DataFrame) -> pd.Series:
    """
    Returns a boolean Series: True on bars where all 3 conditions are met.

    Conditions:
      1. close < ma200  (price below long-term trend)
      2. RSI(14) was < 30 within the last 5 bars  (recently oversold)
         — RSI recovers faster than MACD confirms, so we use a lookback window
      3. MACD(12,26,9) bullish crossover on this bar (momentum confirmation)
    """
    close     = df["close"]
    ma200     = df["ma200"]
    rsi       = df["rsi"]
    macd      = df["macd"]
    macd_sig  = df["macd_signal"]

    prev_macd = macd.shift(1)
    prev_sig  = macd_sig.shift(1)

    # Condition 1: price below MA200
    cond_ma = close < ma200

    # Condition 2: RSI was oversold in last 5 bars (rolling min)
    rsi_min_5 = rsi.rolling(window=5, min_periods=1).min()
    cond_rsi = rsi_min_5 < 30

    # Condition 3: MACD bullish crossover today
    cond_macd_cross = (macd > macd_sig) & (prev_macd <= prev_sig)

    signal = cond_ma & cond_rsi & cond_macd_cross
    return signal.fillna(False)


def get_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Return only the rows where buy_signal == True."""
    if "buy_signal" not in df.columns:
        df = compute_indicators(df)
    signals = df[df["buy_signal"]].copy()
    signals = signals.reset_index()
    if "date" in signals.columns:
        signals["date"] = pd.to_datetime(signals["date"]).dt.strftime("%Y-%m-%d")
    return signals


def prepare_chart_data(df: pd.DataFrame, period_days: int = 730) -> Tuple[list, list, list, list]:
    """
    Prepares serialisable data for the frontend chart.

    Returns:
        candles    - list of {time, open, high, low, close}
        volumes    - list of {time, value, color}
        ma200_line - list of {time, value}
        signals    - list of {time, price}
    """
    if "buy_signal" not in df.columns:
        df = compute_indicators(df)

    if period_days > 0:
        df = df.tail(period_days)

    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"])

    candles, volumes, ma200_line, signals = [], [], [], []

    prev_close = None
    for idx, row in df.iterrows():
        t = int(row["date"].timestamp())
        c = row["close"]
        if pd.isna(c) or c == 0:
            prev_close = c
            continue

        candles.append({
            "time":  t,
            "open":  round(float(row["open"]),  2),
            "high":  round(float(row["high"]),  2),
            "low":   round(float(row["low"]),   2),
            "close": round(float(c),            2),
        })

        vol_color = "#10b981" if (prev_close is None or float(c) >= float(prev_close)) else "#ef4444"
        volumes.append({
            "time":  t,
            "value": float(row["volume"]) if not pd.isna(row["volume"]) else 0,
            "color": vol_color,
        })

        if not pd.isna(row.get("ma200")):
            ma200_line.append({"time": t, "value": round(float(row["ma200"]), 2)})

        if row.get("buy_signal") is True or row.get("buy_signal") == True:
            signals.append({
                "time":  t,
                "price": round(float(row["low"]) * 0.99, 2),
                "close": round(float(c), 2),
            })

        prev_close = c

    return candles, volumes, ma200_line, signals
