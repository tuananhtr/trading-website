"""
backtest.py - Backtesting engine for the MA200 + RSI + MACD strategy.

Trade rules:
  - Entry: Open price of the bar AFTER the buy signal bar
  - S1 exit: Latest close for active positions, or selected stop loss
  - S2 exit: MACD crosses below its signal line; sell at next bar's open,
             or selected stop loss if reached first
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

from strategy import compute_indicators, detect_macd_cross_down

logger = logging.getLogger(__name__)

# Fee model — configurable
BUY_FEE = 0.0015   # 0.15% on entry
SELL_FEE = 0.0015  # 0.15% brokerage on exit
SELL_TAX = 0.001   # 0.10% transfer tax on exit
BOARD_LOT = 100     # HOSE/HNX standard board lot


def run_backtest(
    df: pd.DataFrame,
    ticker: str,
    cut_loss_pct: Optional[float] = None,
    allocation_per_signal: float = 100_000_000,
    strategy: int = 1,
) -> dict:
    """
    Run backtest on *df* OHLCV data.

    Args:
        df           : Full OHLCV DataFrame (DatetimeIndex)
        ticker       : Ticker symbol (display only)
        cut_loss_pct : Optional stop-loss threshold (e.g. 0.07 = 7% loss)
        allocation_per_signal: Cash budget in VND for every buy signal. Each
            signal receives this budget independently; available cash is not
            shared or capped across concurrent signals.
        strategy     : 1 = Oversold reversal; 2 = MACD momentum with cross-down exit

    Returns a dict with:
        summary : dict of aggregate metrics
        trades  : list of per-trade dicts
    """
    if df.empty or len(df) < 200:
        return {"summary": {}, "trades": []}

    # Compute indicators if not already done
    if "buy_signal" not in df.columns or (
        strategy == 2 and not {"macd", "macd_signal"}.issubset(df.columns)
    ):
        df = compute_indicators(df, strategy=strategy)

    df = df.copy()
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"])

    if strategy == 2:
        # A cross must occur on this bar, rather than MACD merely staying below.
        df["macd_cross_down"] = detect_macd_cross_down(df)

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

        # Walk chronologically so a stop loss cannot override an earlier MACD
        # exit. S2 also checks the entry bar's close for a bearish crossover.
        if cut_loss_pct is not None or strategy == 2:
            sl_price = entry_price * (1 - cut_loss_pct) if cut_loss_pct is not None else None
            scan_start = i + 1 if strategy == 2 else i + 2
            for j in range(scan_start, len(df)):
                future_row = df.iloc[j]
                # An intrabar stop precedes a crossover confirmed at the close.
                if sl_price is not None and float(future_row["low"]) <= sl_price:
                    exit_price = sl_price  # Assume filled at SL
                    exit_date = future_row["date"].date()
                    is_active = False
                    exit_reason = f"Stop-Loss ({cut_loss_pct*100:.0f}%)"
                    break

                if strategy == 2 and future_row["macd_cross_down"] and j + 1 < len(df):
                    # The crossover is known at the close. Fill at the next open
                    # (same timing convention as entries); a final-bar cross
                    # remains active until an execution bar exists.
                    exit_row = df.iloc[j + 1]
                    exit_price = float(exit_row["open"])
                    exit_date = exit_row["date"].date()
                    is_active = False
                    exit_reason = "MACD Cross Down"
                    break

        # Fixed-notional position sizing. Spend the same budget on every signal
        # and round down to a tradable 100-share board lot, including the buy
        # fee in the affordability check.
        shares = int(allocation_per_signal / (entry_price * (1 + BUY_FEE)) / BOARD_LOT) * BOARD_LOT
        if shares <= 0:
            continue

        entry_notional = shares * entry_price
        entry_fee = entry_notional * BUY_FEE
        invested_vnd = entry_notional + entry_fee
        exit_notional = shares * exit_price
        exit_fee_and_tax = exit_notional * (SELL_FEE + SELL_TAX)
        exit_proceeds_vnd = exit_notional - exit_fee_and_tax
        net_pnl_vnd = exit_proceeds_vnd - invested_vnd

        # Calculate returns
        days_held = (exit_date - entry_date).days
        gross_pct = (exit_price - entry_price) / entry_price  # decimal
        net_pct = net_pnl_vnd / invested_vnd

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
            "shares": shares,
            "allocation_vnd": round(allocation_per_signal, 0),
            "invested_vnd": round(invested_vnd, 0),
            "net_pnl_vnd": round(net_pnl_vnd, 0),
            "net_pnl_abs": round(net_pnl_vnd, 0),
        })

    # ---------- Summary ----------
    summary = _compute_summary(trades)
    summary["ticker"] = ticker
    summary["fee_model"] = {
        "buy_fee_pct": BUY_FEE * 100,
        "sell_fee_pct": SELL_FEE * 100,
        "sell_tax_pct": SELL_TAX * 100,
    }
    summary["allocation_per_signal_vnd"] = round(allocation_per_signal, 0)

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
            "total_invested_vnd": 0,
            "total_net_pnl_vnd": 0,
            "return_on_deployed_pct": 0,
        }

    gross_pcts = [t["gross_pnl_pct"] for t in trades]
    net_pcts = [t["net_pnl_pct"] for t in trades]
    days = [t["days_held"] for t in trades]
    invested = [t.get("invested_vnd", 0) for t in trades]
    net_pnl_vnd = [t.get("net_pnl_vnd", 0) for t in trades]
    winners = [p for p in gross_pcts if p > 0]
    losers = [p for p in gross_pcts if p <= 0]
    net_winners = [p for p in net_pcts if p > 0]
    net_losers = [p for p in net_pcts if p <= 0]

    total_trades = len(trades)

    # These are signal-level aggregates, not a portfolio simulation: multiple
    # signals can be open at once. Keep the values for analysis, but the UI
    # must not present them as investable compounded portfolio return.
    total_gross_pct = sum(gross_pcts)
    total_net_pct   = sum(net_pcts)
    gross_profit = sum(net_winners)
    gross_loss = abs(sum(net_losers))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss else None
    total_invested_vnd = sum(invested)
    total_net_pnl_vnd = sum(net_pnl_vnd)

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
        "median_hold_days": round(float(pd.Series(days).median()), 1) if days else 0,
        "median_net_pnl_pct": round(float(pd.Series(net_pcts).median()), 2) if net_pcts else 0,
        "profit_factor": profit_factor,
        "active_trades": sum(1 for t in trades if t["is_active"]),
        "closed_trades": sum(1 for t in trades if not t["is_active"]),
        "total_invested_vnd": round(total_invested_vnd, 0),
        "total_net_pnl_vnd": round(total_net_pnl_vnd, 0),
        "return_on_deployed_pct": round(total_net_pnl_vnd / total_invested_vnd * 100, 2) if total_invested_vnd else 0,
    }
