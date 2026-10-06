/**
 * api.js — REST API wrapper for the trading dashboard backend.
 */

// Empty string = relative URL → works on both localhost and Railway (same origin)
const BASE = "";

async function apiFetch(path, opts = {}) {
  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "API error");
  }
  return res.json();
}

const API = {
  /** Get OHLCV + indicators for a ticker */
  getStockData(ticker, period = "2Y", strategy = 1) {
    return apiFetch(`/api/stocks/${ticker}/data?period=${period}&strategy=${strategy}`);
  },

  /** Get all buy signals */
  getSignals(ticker, strategy = 1) {
    return apiFetch(`/api/stocks/${ticker}/signals?strategy=${strategy}`);
  },

  /** Run backtest, optionally filtered to a time period */
  getBacktest(ticker, cutLoss = null, period = "ALL", strategy = 1) {
    const params = new URLSearchParams();
    if (cutLoss != null) params.set("cut_loss", cutLoss);
    if (period)          params.set("period", period);
    params.set("strategy", strategy);
    return apiFetch(`/api/stocks/${ticker}/backtest?${params.toString()}`);
  },

  /** Force re-fetch from yfinance */
  refreshStock(ticker) {
    return apiFetch(`/api/stocks/${ticker}/refresh`, { method: "POST" });
  },

  /** Watchlist CRUD */
  getWatchlist() {
    return apiFetch("/api/watchlist");
  },
  addToWatchlist(ticker) {
    return apiFetch(`/api/watchlist/${ticker}`, { method: "POST" });
  },
  removeFromWatchlist(ticker) {
    return apiFetch(`/api/watchlist/${ticker}`, { method: "DELETE" });
  },

  /** Search tickers */
  searchTickers(q) {
    return apiFetch(`/api/stocks/search?q=${encodeURIComponent(q)}`);
  },

  /** VN30 ranking: 5Y backtest for all 30 stocks */
  getVn30Ranking(strategy = 1, forceRefresh = false) {
    return apiFetch(`/api/vn30/ranking?strategy=${strategy}&refresh=${forceRefresh}`);
  },

  /** Trigger background re-download of all VN30 prices */
  refreshVn30() {
    return apiFetch("/api/vn30/refresh", { method: "POST" });
  },
};

window.API = API;
