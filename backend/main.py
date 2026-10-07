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
from strategy import compute_indicators, get_signals, prepare_chart_data, prepare_sell_signals
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
# Frontend dir: try ../frontend (standard), fall back to ./frontend
_base = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(_base, "..", "frontend")
if not os.path.isdir(FRONTEND_DIR):
    FRONTEND_DIR = os.path.join(_base, "frontend")

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
    strategy: int = Query(1, description="1=Oversold Reversal, 2=MACD Momentum"),
):
    """Return OHLCV + indicators formatted for the chart."""
    ticker = ticker.upper()
    period_days = PERIOD_MAP.get(period.upper(), 730)

    df = get_or_fetch(ticker)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data found for {ticker}")

    df = compute_indicators(df, strategy=strategy)

    # Always return ALL candles so user can zoom out to see full history.
    candles, volumes, ma200, signals = prepare_chart_data(df, period_days=0)
    # Include full-history sell signals too, so they remain visible on zoom out.
    sell_signals = prepare_sell_signals(df)

    # Latest price info
    last_close = float(df["close"].iloc[-1]) if not df.empty else 0
    prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else last_close
    change = last_close - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0

    # Send the period cutoff timestamp so the frontend can set initial visible range
    period_from_ts = int((pd.Timestamp.now() - pd.Timedelta(days=period_days)).timestamp()) if period_days > 0 else 0

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
        "sell_signals": sell_signals,
        "strategy": strategy,
        "period": period,
        "period_from_ts": period_from_ts,
    }


@app.get("/api/stocks/{ticker}/signals")
def get_stock_signals(
    ticker: str,
    strategy: int = Query(1, description="1=Oversold Reversal, 2=MACD Momentum"),
):
    """Return all buy signals (date + price) for a ticker."""
    ticker = ticker.upper()
    df = get_or_fetch(ticker)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data for {ticker}")

    df = compute_indicators(df, strategy=strategy)
    sigs = get_signals(df)

    result = []
    for _, row in sigs.iterrows():
        result.append({
            "date":  str(row.get("date", "")),
            "close": round(float(row["close"]), 2) if not pd.isna(row["close"]) else None,
            "rsi":   round(float(row["rsi"]),   2) if not pd.isna(row["rsi"])   else None,
            "macd":  round(float(row["macd"]),  4) if not pd.isna(row["macd"])  else None,
            "ma200": round(float(row["ma200"]), 2) if not pd.isna(row["ma200"]) else None,
        })

    return {"ticker": ticker, "signals": result, "count": len(result), "strategy": strategy}


@app.get("/api/stocks/{ticker}/backtest")
def get_backtest(
    ticker: str,
    cut_loss: Optional[float] = Query(None, description="Stop-loss %, e.g. 7 for 7%"),
    period: str = Query("ALL", description="Time period filter: 1M|3M|6M|1Y|2Y|5Y|ALL"),
    strategy: int = Query(1, description="1=Oversold Reversal, 2=MACD Momentum"),
    allocation: float = Query(100_000_000, gt=0, le=10_000_000_000, description="VND allocated independently to each signal"),
):
    """Run backtest and return summary + detail tables, filtered to the selected period."""
    ticker = ticker.upper()
    df = get_or_fetch(ticker)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data for {ticker}")

    # Always compute indicators on FULL data so MA200/RSI/MACD have enough bars.
    # Filtering the df first would leave < 200 rows for short periods like 1M/3M/6M.
    df = compute_indicators(df, strategy=strategy)

    cut_loss_decimal = cut_loss / 100 if cut_loss else None
    result = run_backtest(
        df,
        ticker=ticker,
        cut_loss_pct=cut_loss_decimal,
        allocation_per_signal=allocation,
        strategy=strategy,
    )

    # Filter trades by signal_date AFTER backtest runs on full data
    period_days = PERIOD_MAP.get(period.upper(), 0)
    if period_days > 0:
        cutoff = (pd.Timestamp.now() - pd.Timedelta(days=period_days)).date()
        result["trades"] = [
            t for t in result["trades"]
            if pd.to_datetime(t["signal_date"]).date() >= cutoff
        ]
        # Recompute summary on the filtered trades
        from backtest import _compute_summary
        result["summary"] = _compute_summary(result["trades"])
        result["summary"]["ticker"] = ticker
        result["summary"]["allocation_per_signal_vnd"] = round(allocation, 0)

    # Buy-and-hold makes the strategy output interpretable in market context.
    # It is intentionally calculated over the same selected calendar window.
    window_df = df
    if period_days > 0:
        window_df = df[df.index >= pd.Timestamp(cutoff)]
    if len(window_df) >= 2:
        start_close = float(window_df["close"].iloc[0])
        end_close = float(window_df["close"].iloc[-1])
        benchmark_return = ((end_close / start_close) - 1) * 100 if start_close else 0
        elapsed_years = max((window_df.index[-1] - window_df.index[0]).days / 365.25, 0)
        benchmark_cagr = ((end_close / start_close) ** (1 / elapsed_years) - 1) * 100 if elapsed_years and start_close else 0
        equity = window_df["close"] / start_close
        benchmark_drawdown = ((equity / equity.cummax()) - 1).min() * 100
        result["summary"].update({
            "benchmark_return_pct": round(benchmark_return, 2),
            "benchmark_cagr_pct": round(benchmark_cagr, 2),
            "benchmark_max_drawdown_pct": round(float(benchmark_drawdown), 2),
            "benchmark_start_date": window_df.index[0].strftime("%Y-%m-%d"),
            "benchmark_end_date": window_df.index[-1].strftime("%Y-%m-%d"),
        })

    result["period"] = period
    result["strategy"] = strategy
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

# ---- VN30 Ranking ----

VN30_TICKERS = [
    "VIC", "VHM", "VCB", "BID", "TCB", "CTG", "VPB", "GAS", "MBB", "HPG",
    "VPL", "HDB", "GVR", "LPB", "STB", "ACB", "VNM", "FPT", "MSN", "MWG",
    "VJC", "SSB", "SHB", "SSI", "SAB", "VRE", "VIB", "PLX", "TPB", "DGC",
]

# In-memory ranking cache  {strategy_int: {"payload": dict, "ts": datetime}}
_vn30_cache: dict = {}


@app.get("/api/vn30/ranking")
def get_vn30_ranking(
    strategy: int = Query(1, description="1=Oversold, 2=Momentum"),
    refresh: bool = Query(False),
):
    """
    Run 5-year backtest for every VN30 stock and return ranked by
    average net P&L per trade.  Results are cached for 1 hour.
    """
    from datetime import datetime as _dt
    from backtest import _compute_summary

    now = _dt.utcnow()
    cached = _vn30_cache.get(strategy)
    if not refresh and cached:
        age_s = (now - cached["ts"]).total_seconds()
        if age_s < 3600:
            return cached["payload"]

    cutoff_5y = (pd.Timestamp.now() - pd.Timedelta(days=1825)).date()
    results = []

    for ticker in VN30_TICKERS:
        try:
            df = get_or_fetch(ticker)
            if df.empty or len(df) < 200:
                results.append({"ticker": ticker, "status": "no_data",
                                 "last_close": None, "total_trades": 0})
                continue

            df_ind = compute_indicators(df, strategy=strategy)
            bt = run_backtest(df_ind, ticker=ticker, strategy=strategy)

            # Filter trades to last 5 years
            trades_5y = [
                t for t in bt.get("trades", [])
                if pd.to_datetime(t["signal_date"]).date() >= cutoff_5y
            ]
            summary = _compute_summary(trades_5y)
            last_close = float(df["close"].iloc[-1])

            results.append({
                "ticker": ticker,
                "status": "ok",
                "last_close": round(last_close, 0),
                "total_trades": summary["total_trades"],
                "win_rate_pct": summary["win_rate_pct"],
                "avg_net_pnl_pct": summary["avg_net_pnl_pct"],
                "avg_gross_pnl_pct": summary["avg_gross_pnl_pct"],
                "total_net_pnl_pct": summary["total_net_pnl_pct"],
                "best_trade_pct": summary["best_trade_pct"],
                "worst_trade_pct": summary["worst_trade_pct"],
                "avg_hold_days": summary["avg_hold_days"],
            })
        except Exception as exc:
            logger.error(f"VN30 ranking [{ticker}]: {exc}")
            results.append({"ticker": ticker, "status": "error",
                             "last_close": None, "total_trades": 0})

    # Rank by avg_net_pnl_pct; stocks with signals first, rest at bottom
    has_signal = sorted(
        [r for r in results if r.get("status") == "ok" and r["total_trades"] > 0],
        key=lambda x: x["avg_net_pnl_pct"], reverse=True,
    )
    no_signal  = [r for r in results if r.get("status") == "ok" and r["total_trades"] == 0]
    errored    = [r for r in results if r.get("status") not in ("ok",)]

    for i, r in enumerate(has_signal, 1):
        r["rank"] = i

    payload = {
        "strategy": strategy,
        "period": "5Y",
        "updated_at": now.isoformat() + "Z",
        "results": has_signal + no_signal + errored,
        "ranked_count": len(has_signal),
    }
    _vn30_cache[strategy] = {"payload": payload, "ts": now}
    return payload


@app.post("/api/vn30/refresh")
def refresh_vn30(background_tasks: BackgroundTasks):
    """Trigger background incremental update for all VN30 stocks."""
    background_tasks.add_task(_vn30_refresh_task)
    return {"message": "VN30 refresh started", "tickers": VN30_TICKERS}


def _vn30_refresh_task():
    """Download / update data for all 30 VN30 stocks, then clear ranking cache."""
    from data_fetcher import incremental_update as _inc
    for t in VN30_TICKERS:
        try:
            _inc(t)
            logger.info(f"[VN30] {t} updated")
        except Exception as e:
            logger.warning(f"[VN30] {t} failed: {e}")
    _vn30_cache.clear()
    logger.info("[VN30] All stocks refreshed, cache cleared")


@app.on_event("startup")
async def _startup():
    """On every server start, kick off a background VN30 refresh (daily update)."""
    import threading
    threading.Thread(target=_vn30_refresh_task, daemon=True).start()


@app.get("/api/vn30/signals")
def get_vn30_recent_signals(
    strategy: int = Query(1, description="1=Oversold, 2=Momentum"),
    days: int = Query(30, description="Look-back window in days"),
):
    """Return VN30 stocks that fired a buy signal within the last N days."""
    cutoff = (pd.Timestamp.now() - pd.Timedelta(days=days)).date()
    results = []

    for ticker in VN30_TICKERS:
        try:
            df = get_or_fetch(ticker)
            if df.empty or len(df) < 200:
                continue
            df_ind = compute_indicators(df, strategy=strategy)
            bt = run_backtest(df_ind, ticker=ticker, strategy=strategy)
            recent = [
                t for t in bt.get("trades", [])
                if pd.to_datetime(t["signal_date"]).date() >= cutoff
            ]
            results.extend(recent)
        except Exception as exc:
            logger.warning(f"VN30 signals [{ticker}]: {exc}")

    results.sort(key=lambda x: x["signal_date"], reverse=True)
    return {
        "strategy": strategy,
        "days": days,
        "count": len(results),
        "results": results,
    }


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
