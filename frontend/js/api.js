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
  getStockData(ticker, period = "2Y") {
    return apiFetch(`/api/stocks/${ticker}/data?period=${period}`);
  },

  /** Get all buy signals */
  getSignals(ticker) {
    return apiFetch(`/api/stocks/${ticker}/signals`);
  },

  /** Run backtest, optionally filtered to a time period */
  getBacktest(ticker, cutLoss = null, period = "ALL") {
    const params = new URLSearchParams();
    if (cutLoss != null) params.set("cut_loss", cutLoss);
    if (period)          params.set("period", period);
    const qs = params.toString() ? "?" + params.toString() : "";
    return apiFetch(`/api/stocks/${ticker}/backtest${qs}`);
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
};

window.API = API;
