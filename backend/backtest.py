"""
backtest.py - Backtesting engine for the MA200 + RSI + MACD strategy.

Trade rules:
  - Entry: Open price of the bar AFTER the buy signal bar
  - Exit:  Today's last close price (open position) OR
           when another condition triggers (future extension)
  - Tax / Fee model (Vietnam):
      Buy-side:  0.15% brokerage fee
      Sell-side: 0.15% brokerage fee + 0.1% securities transfer tax
      Total round-trip cost: ~0.40%
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import pandas as pd

from strategy import compute_indicators

logger = logging.getLogger(__name__)

# Fee model — configurable
BUY_FEE = 0.0015   # 0.15% on entry
SELL_FEE = 0.0015  # 0.15% brokerage on exit
SELL_TAX = 0.001   # 0.10% transfer tax on exit


def run_backtest(
    df: pd.DataFrame,
    ticker: str,
    cut_loss_pct: Optional[float] = None,
) -> dict:
    """
    Run backtest on *df* OHLCV data.

    Args:
        df           : Full OHLCV DataFrame (DatetimeIndex)
        ticker       : Ticker symbol (display only)
        cut_loss_pct : Optional stop-loss threshold (e.g. 0.07 = 7% loss)

    Returns a dict with:
        summary : dict of aggregate metrics
        trades  : list of per-trade dicts
    """
    if df.empty or len(df) < 200:
        return {"summary": {}, "trades": []}

    # Compute indicators if not already done
    if "buy_signal" not in df.columns:
        df = compute_indicators(df)

    df = df.copy()
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"])

    today_price = float(df["close"].iloc[-1])
    today_date = df["date"].iloc[-1].date()

    trades = []

    for i, row in df.iterrows():
        if not row.get("buy_signal", False):
            continue

        signal_date = row["date"].date()

        # Entry: open of the NEXT bar
        if i + 1 >= len(df):
            continue  # Signal on last bar — can't enter
        entry_row = df.iloc[i + 1]
        entry_price = float(entry_row["open"])
        entry_date = entry_row["date"].date()

        if entry_price <= 0:
            continue

        # Determine exit
        exit_price = today_price
        exit_date = today_date
        is_active = True
        exit_reason = "Active"

        # Apply stop-loss if configured
        if cut_loss_pct is not None:
            sl_price = entry_price * (1 - cut_loss_pct)
            # Scan forward from entry for stop-loss breach
            for j in range(i + 2, len(df)):
                future_row = df.iloc[j]
                if float(future_row["low"]) <= sl_price:
                    exit_price = sl_price  # Assume filled at SL
                    exit_date = future_row["date"].date()
                    is_active = False
                    exit_reason = f"Stop-Loss ({cut_loss_pct*100:.0f}%)"
                    break

        # Calculate returns
        days_held = (exit_date - entry_date).days
        gross_pct = (exit_price - entry_price) / entry_price  # decimal

        # Net after fees and taxes
        buy_cost = entry_price * BUY_FEE
        sell_cost = exit_price * (SELL_FEE + SELL_TAX)
        net_pct = ((exit_price - sell_cost) - (entry_price + buy_cost)) / (entry_price + buy_cost)

        trades.append({
            "signal_date": signal_date.strftime("%Y-%m-%d"),
            "entry_date": entry_date.strftime("%Y-%m-%d"),
            "ticker": ticker,
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "exit_date": exit_date.strftime("%Y-%m-%d"),
            "is_active": is_active,
            "exit_reason": exit_reason,
            "days_held": days_held,
            "gross_pnl_pct": round(gross_pct * 100, 2),
            "net_pnl_pct": round(net_pct * 100, 2),
            "gross_pnl_abs": round(exit_price - entry_price, 2),
            "net_pnl_abs": round((exit_price - sell_cost) - (entry_price + buy_cost), 2),
        })

    # ---------- Summary ----------
    summary = _compute_summary(trades)
    summary["ticker"] = ticker
    summary["fee_model"] = {
        "buy_fee_pct": BUY_FEE * 100,
        "sell_fee_pct": SELL_FEE * 100,
        "sell_tax_pct": SELL_TAX * 100,
    }

    return {"summary": summary, "trades": sorted(trades, key=lambda x: x["signal_date"], reverse=True)}


def _compute_summary(trades: list) -> dict:
    if not trades:
        return {
            "total_trades": 0,
            "win_rate_pct": 0,
            "total_gross_pnl_pct": 0,
            "total_net_pnl_pct": 0,
            "best_trade_pct": 0,
            "worst_trade_pct": 0,
            "avg_hold_days": 0,
            "avg_gross_pnl_pct": 0,
            "avg_net_pnl_pct": 0,
            "profitable_trades": 0,
            "losing_trades": 0,
        }

    gross_pcts = [t["gross_pnl_pct"] for t in trades]
    net_pcts = [t["net_pnl_pct"] for t in trades]
    days = [t["days_held"] for t in trades]
    winners = [p for p in gross_pcts if p > 0]
    losers = [p for p in gross_pcts if p <= 0]

    total_trades = len(trades)

    # Simple total return (sum of all trade P&Ls — not compounded)
    total_gross_pct = sum(gross_pcts)
    total_net_pct   = sum(net_pcts)

    return {
        "total_trades": total_trades,
        "profitable_trades": len(winners),
        "losing_trades": len(losers),
        "win_rate_pct": round(len(winners) / total_trades * 100, 1) if total_trades else 0,
        "total_gross_pnl_pct": round(total_gross_pct, 2),
        "total_net_pnl_pct": round(total_net_pct, 2),
        "avg_gross_pnl_pct": round(sum(gross_pcts) / total_trades, 2),
        "avg_net_pnl_pct": round(sum(net_pcts) / total_trades, 2),
        "best_trade_pct": round(max(gross_pcts), 2),
        "worst_trade_pct": round(min(gross_pcts), 2),
        "avg_hold_days": round(sum(days) / total_trades, 1) if total_trades else 0,
    }
