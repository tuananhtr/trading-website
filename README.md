# 🇻🇳 Vietnam Stock Trading Dashboard

A dark-themed trading dashboard for Vietnam stock market (HOSE/HNX) with buy signal detection, interactive charting, and backtesting.

![Dashboard Preview](preview.png)

## Features

- 📈 **Interactive candlestick chart** — TradingView Lightweight Charts with MA200 overlay and volume bars
- 🟡 **Buy signal detection** — MA200 + RSI(14) < 30 + MACD(12,26,9) crossover strategy
- 📊 **Backtesting** — per-trade P&L table with Vietnam tax/fee model (0.40% round-trip)
- 📋 **Watchlist** — persistent watchlist saved in local SQLite database
- 🗄️ **Local database** — all stock OHLCV data stored in SQLite from 2010, fetched once from yfinance
- ⏱️ **Period filter** — 1M / 3M / 6M / 1Y / 2Y / 5Y / ALL filters chart and backtest table together
- ✂️ **Cut-loss filter** — simulate stop-loss at 7% / 10% / 15%

## Strategy

| Condition | Rule |
|-----------|------|
| Trend | Close price **below MA(200)** |
| Momentum | **RSI(14) < 30** (oversold, within last 5 bars) |
| Confirmation | **MACD(12,26,9)** line crosses **above** signal line |
| Entry | Open of next bar after signal |
| Exit | Current price (open position) |

## Tech Stack

- **Backend**: Python + FastAPI + SQLite (SQLAlchemy) + yfinance + pandas
- **Frontend**: HTML + CSS + Vanilla JS + TradingView Lightweight Charts v4

## Setup

### 1. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Start the server

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Open in browser

```
http://localhost:8000
```

The first time you add a stock to the watchlist, data is downloaded from yfinance (~10–30s). After that all data is served from the local SQLite database.

## Project Structure

```
trading-website/
├── backend/
│   ├── main.py          # FastAPI server & API routes
│   ├── database.py      # SQLite ORM (stock prices + watchlist)
│   ├── data_fetcher.py  # yfinance downloader
│   ├── strategy.py      # MA200 + RSI + MACD signal detection
│   ├── backtest.py      # Backtesting engine
│   └── requirements.txt
└── frontend/
    ├── index.html
    ├── css/style.css
    └── js/
        ├── app.js        # Main app controller
        ├── chart.js      # TradingView chart integration
        └── api.js        # REST API wrapper
```

## Fee Model (Vietnam)

| Side | Rate |
|------|------|
| Buy brokerage | 0.15% |
| Sell brokerage | 0.15% |
| Securities transfer tax (sell) | 0.10% |
| **Total round-trip** | **~0.40%** |
