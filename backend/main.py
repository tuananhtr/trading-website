"""
main.py - FastAPI server for the Vietnam Stock Trading Dashboard.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from database import (
    init_db,
    get_ohlcv,
    get_watchlist,
    add_to_watchlist,
    remove_from_watchlist,
    has_data,
)
from data_fetcher import fetch_and_store, incremental_update, get_or_fetch
from strategy import compute_indicators, get_signals, prepare_chart_data
from backtest import run_backtest

# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Init DB on startup
init_db()

app = FastAPI(title="Vietnam Stock Trading Dashboard", version="1.0.0")

# CORS — allow the frontend (served from same origin or dev server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
PERIOD_MAP = {
    "1M": 30,
    "3M": 90,
    "6M": 180,
    "1Y": 365,
    "2Y": 730,
    "5Y": 1825,
    "ALL": 0,
}


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---- Stock Data ----

@app.get("/api/stocks/{ticker}/data")
def get_stock_data(
    ticker: str,
    period: str = Query("2Y", description="1M|3M|6M|1Y|2Y|5Y|ALL"),
):
    """Return OHLCV + indicators formatted for the chart."""
    ticker = ticker.upper()
    period_days = PERIOD_MAP.get(period.upper(), 730)

    df = get_or_fetch(ticker)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data found for {ticker}")

    df = compute_indicators(df)

    candles, volumes, ma200, signals = prepare_chart_data(df, period_days=period_days)

    # Latest price info
    last_close = float(df["close"].iloc[-1]) if not df.empty else 0
    prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else last_close
    change = last_close - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0

    return {
        "ticker": ticker,
        "last_close": round(last_close, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "signal_count": len(signals),
        "candles": candles,
        "volumes": volumes,
        "ma200": ma200,
        "signals": signals,
    }


@app.get("/api/stocks/{ticker}/signals")
def get_stock_signals(ticker: str):
    """Return all buy signals (date + price) for a ticker."""
    ticker = ticker.upper()
    df = get_or_fetch(ticker)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data for {ticker}")

    df = compute_indicators(df)
    sigs = get_signals(df)

    result = []
    for _, row in sigs.iterrows():
        result.append({
            "date": str(row.get("date", "")),
            "close": round(float(row["close"]), 2) if not pd.isna(row["close"]) else None,
            "rsi": round(float(row["rsi"]), 2) if not pd.isna(row["rsi"]) else None,
            "macd": round(float(row["macd"]), 4) if not pd.isna(row["macd"]) else None,
            "ma200": round(float(row["ma200"]), 2) if not pd.isna(row["ma200"]) else None,
        })

    return {"ticker": ticker, "signals": result, "count": len(result)}


@app.get("/api/stocks/{ticker}/backtest")
def get_backtest(
    ticker: str,
    cut_loss: Optional[float] = Query(None, description="Stop-loss %, e.g. 7 for 7%"),
    period: str = Query("ALL", description="Time period filter: 1M|3M|6M|1Y|2Y|5Y|ALL"),
):
    """Run backtest and return summary + detail tables, filtered to the selected period."""
    ticker = ticker.upper()
    df = get_or_fetch(ticker)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data for {ticker}")

    df = compute_indicators(df)

    # Filter by actual calendar date so "2Y" means exactly 2 calendar years back
    period_days = PERIOD_MAP.get(period.upper(), 0)
    if period_days > 0:
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=period_days)
        df = df[df.index >= cutoff]

    cut_loss_decimal = cut_loss / 100 if cut_loss else None
    result = run_backtest(df, ticker=ticker, cut_loss_pct=cut_loss_decimal)
    result["period"] = period
    return result


@app.post("/api/stocks/{ticker}/refresh")
def refresh_stock(ticker: str, background_tasks: BackgroundTasks):
    """Force re-download from yfinance."""
    ticker = ticker.upper()
    background_tasks.add_task(fetch_and_store, ticker, force=True)
    return {"status": "refresh_started", "ticker": ticker}


# ---- Watchlist ----

@app.get("/api/watchlist")
def get_watchlist_route():
    return {"watchlist": get_watchlist()}


@app.post("/api/watchlist/{ticker}")
def add_watchlist(ticker: str):
    ticker = ticker.upper()
    # Trigger initial data fetch in background if needed
    if not has_data(ticker):
        fetch_and_store(ticker)
    ok = add_to_watchlist(ticker)
    return {"added": ok, "ticker": ticker}


@app.delete("/api/watchlist/{ticker}")
def remove_watchlist(ticker: str):
    ticker = ticker.upper()
    ok = remove_from_watchlist(ticker)
    if not ok:
        raise HTTPException(status_code=404, detail="Ticker not in watchlist")
    return {"removed": True, "ticker": ticker}


# ---- Search ----

# Popular VN stocks list (HOSE + HNX top tickers)
VN_TICKERS = [
    "HPG", "VNM", "FPT", "MWG", "VIC", "VHM", "MSN", "TCB", "VCB", "BID",
    "CTG", "MBB", "ACB", "HDB", "VPB", "STB", "EIB", "SHB", "NVL", "PDR",
    "GVR", "SAB", "VGC", "DGC", "PVD", "PLX", "GAS", "POW", "PPC", "NT2",
    "DHC", "HAG", "HNG", "IDI", "KDC", "KDH", "LGC", "MPC", "NAB", "PAN",
    "REE", "SCS", "SSI", "VCI", "VDS", "VND", "VNS", "VSH", "YEG", "DXG",
    "DXS", "AGR", "ANV", "ASM", "BCM", "BSI", "CII", "CMG", "CSV", "CTD",
    "DBC", "DCM", "DIG", "DPM", "EVF", "FCN", "GMD", "HCM", "HDG", "HII",
    "HMC", "HSG", "HTN", "HVN", "IMP", "KBC", "KSB", "LCG", "LDG", "MSB",
    "NKG", "OGC", "OCB", "PNJ", "PTB", "QCG", "SBT", "SKG", "SVC", "TCD",
    "TCH", "TLG", "TMT", "TPB", "TVS", "VEA", "VHC", "VIB", "VIP", "VJC",
    "VMD", "VNE", "VOS", "VRC", "VSC", "VTO", "WHS", "AAA", "ADS", "APH",
]


@app.get("/api/stocks/search")
def search_tickers(q: str = Query("", min_length=0)):
    q = q.upper().strip()
    if not q:
        return {"results": VN_TICKERS[:20]}
    matches = [t for t in VN_TICKERS if q in t]
    return {"results": matches[:20]}


# ---- Serve Frontend ----

@app.get("/")
def serve_frontend():
    index = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"message": "Frontend not found"}


@app.get("/{path:path}")
def serve_static(path: str):
    file_path = os.path.join(FRONTEND_DIR, path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="File not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
