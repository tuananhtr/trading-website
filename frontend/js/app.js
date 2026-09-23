/**
 * app.js — Main application controller for the Vietnam Trading Dashboard.
 * Manages: watchlist, stock selection, chart rendering, backtest tables.
 */

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
  activeTicker: null,
  watchlist: [],
  period: "2Y",
  cutLoss: null,
  loading: false,
  backtestData: null,
  stockData: null,
};

// ─── DOM refs ────────────────────────────────────────────────────────────────
const dom = {
  pillsContainer: () => document.getElementById("watchlist-pills"),
  searchInput: () => document.getElementById("search-input"),
  searchDropdown: () => document.getElementById("search-dropdown"),
  stockTicker: () => document.getElementById("stock-ticker"),
  stockPrice: () => document.getElementById("stock-price"),
  stockChange: () => document.getElementById("stock-change"),
  signalBadge: () => document.getElementById("signal-badge"),
  chartLoading: () => document.getElementById("chart-loading"),
  summaryCards: () => document.getElementById("summary-cards"),
  signalTableBody: () => document.getElementById("signal-table-body"),
  backtest2Y: () => document.getElementById("backtest-period-label"),
  toastContainer: () => document.getElementById("toast-container"),
  refreshBtn: () => document.getElementById("btn-refresh"),
};

// ─── Toast ───────────────────────────────────────────────────────────────────
function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  dom.toastContainer().appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ─── Format helpers ───────────────────────────────────────────────────────────
function fmt(n, decimals = 2) {
  if (n == null || isNaN(n)) return "—";
  return Number(n).toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function fmtPct(n) {
  if (n == null || isNaN(n)) return "—";
  const sign = n >= 0 ? "+" : "";
  return `${sign}${Number(n).toFixed(2)}%`;
}

function pnlClass(n) {
  if (n > 0) return "pnl-pos";
  if (n < 0) return "pnl-neg";
  return "pnl-zero";
}

function pnlSpan(n) {
  const cls = pnlClass(n);
  const prefix = n > 0 ? "▲ +" : n < 0 ? "▼ " : "";
  return `<span class="${cls}">${prefix}${Math.abs(Number(n)).toFixed(2)}%</span>`;
}

// ─── Watchlist ────────────────────────────────────────────────────────────────
async function loadWatchlist() {
  try {
    const data = await API.getWatchlist();
    state.watchlist = data.watchlist || [];
    renderPills();

    // Auto-select first ticker
    if (state.watchlist.length && !state.activeTicker) {
      selectTicker(state.watchlist[0]);
    }
  } catch (e) {
    toast("Could not load watchlist. Is the server running?", "error");
  }
}

function renderPills() {
  const container = dom.pillsContainer();
  if (!container) return;
  container.innerHTML = "";

  state.watchlist.forEach((ticker) => {
    const pill = document.createElement("button");
    pill.className = "pill" + (ticker === state.activeTicker ? " active" : "");
    pill.dataset.ticker = ticker;

    const label = document.createElement("span");
    label.textContent = ticker;

    const removeBtn = document.createElement("span");
    removeBtn.className = "remove-pill";
    removeBtn.textContent = "✕";
    removeBtn.title = "Remove from watchlist";
    removeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      removeTicker(ticker);
    });

    pill.appendChild(label);
    pill.appendChild(removeBtn);
    pill.addEventListener("click", () => selectTicker(ticker));
    container.appendChild(pill);
  });
}

async function addTicker(ticker) {
  ticker = ticker.trim().toUpperCase();
  if (!ticker) return;
  if (state.watchlist.includes(ticker)) {
    toast(`${ticker} is already in watchlist`);
    selectTicker(ticker);
    return;
  }
  try {
    toast(`Fetching data for ${ticker}… (may take a moment)`, "info");
    await API.addToWatchlist(ticker);
    state.watchlist.push(ticker);
    renderPills();
    selectTicker(ticker);
    toast(`${ticker} added to watchlist`, "success");
  } catch (e) {
    toast(`Error adding ${ticker}: ${e.message}`, "error");
  }
}

async function removeTicker(ticker) {
  try {
    await API.removeFromWatchlist(ticker);
    state.watchlist = state.watchlist.filter((t) => t !== ticker);
    if (state.activeTicker === ticker) {
      state.activeTicker = null;
      if (state.watchlist.length) selectTicker(state.watchlist[0]);
      else clearDashboard();
    }
    renderPills();
    toast(`${ticker} removed from watchlist`);
  } catch (e) {
    toast(`Error removing ${ticker}: ${e.message}`, "error");
  }
}

// ─── Stock Selection ──────────────────────────────────────────────────────────
async function selectTicker(ticker) {
  state.activeTicker = ticker;
  renderPills();
  await loadStockData();
}

async function loadStockData() {
  const ticker = state.activeTicker;
  if (!ticker) return;
  if (state.loading) return;

  state.loading = true;
  showChartLoading(true);

  try {
    // Load chart data
    const data = await API.getStockData(ticker, state.period);
    state.stockData = data;
    updateHeader(data);
    ChartManager.updateCharts(data);
    updateSignalBadge(data.signal_count);

    // Load backtest
    await loadBacktest(ticker);
  } catch (e) {
    toast(`Error loading ${ticker}: ${e.message}`, "error");
    console.error(e);
  } finally {
    state.loading = false;
    showChartLoading(false);
  }
}

async function loadBacktest(ticker) {
  try {
    const data = await API.getBacktest(ticker, state.cutLoss, state.period);
    state.backtestData = data;
    renderSummaryCards(data.summary);
    renderSignalTable(data.trades);
    // Update section title to show active period
    const titleEl = document.getElementById("backtest-title");
    if (titleEl) titleEl.textContent = `Buy Signals & Backtest — Last ${state.period}`;
  } catch (e) {
    console.error("Backtest error:", e);
  }
}

function showChartLoading(show) {
  const el = dom.chartLoading();
  if (el) el.classList.toggle("hidden", !show);
}

// ─── Header ──────────────────────────────────────────────────────────────────
function updateHeader(data) {
  const t = dom.stockTicker();
  const p = dom.stockPrice();
  const c = dom.stockChange();
  if (t) t.textContent = data.ticker;
  if (p) p.textContent = fmt(data.last_close, 2);
  if (c) {
    const pct = data.change_pct;
    const sign = pct >= 0 ? "+" : "";
    c.textContent = `${sign}${fmt(Math.abs(data.change), 2)} (${sign}${pct.toFixed(2)}%)`;
    c.className = "stock-change " + (pct > 0 ? "pos" : pct < 0 ? "neg" : "neu");
  }
}

function updateSignalBadge(count) {
  const el = dom.signalBadge();
  if (el) el.innerHTML = `<span>${count}</span> buy signals`;
}

function clearDashboard() {
  const t = dom.stockTicker();
  if (t) t.textContent = "—";
  const p = dom.stockPrice();
  if (p) p.textContent = "";
  const c = dom.stockChange();
  if (c) c.textContent = "";
  renderSummaryCards({});
  renderSignalTable([]);
}

// ─── Summary Cards ────────────────────────────────────────────────────────────
function renderSummaryCards(s) {
  const container = dom.summaryCards();
  if (!container) return;
  if (!s || !Object.keys(s).length) {
    container.innerHTML = '<div class="empty-state"><div class="icon">📊</div>No backtest data yet</div>';
    return;
  }

  const winRateColor = s.win_rate_pct >= 50 ? "pos" : "neg";
  const grossPnlColor = s.total_gross_pnl_pct >= 0 ? "pos" : "neg";
  const netPnlColor = s.total_net_pnl_pct >= 0 ? "pos" : "neg";

  const cards = [
    { label: "Total Trades",     value: s.total_trades ?? 0,           sub: `${s.profitable_trades ?? 0} win / ${s.losing_trades ?? 0} loss`, cls: "" },
    { label: "Win Rate",         value: `${s.win_rate_pct ?? 0}%`,      sub: "Profitable trades",         cls: winRateColor },
    { label: "Avg P&L / Trade",  value: fmtPct(s.avg_gross_pnl_pct),    sub: "Per trade (gross)",         cls: s.avg_gross_pnl_pct >= 0 ? "pos" : "neg" },
    { label: "Best Trade",       value: fmtPct(s.best_trade_pct),        sub: "Single trade",              cls: "pos" },
    { label: "Worst Trade",      value: fmtPct(s.worst_trade_pct),       sub: "Single trade",              cls: "neg" },
    { label: "Avg Hold Days",    value: `${s.avg_hold_days ?? 0}d`,      sub: "Per trade",                 cls: "" },
  ];

  container.innerHTML = cards
    .map(
      (c) => `
    <div class="summary-card">
      <div class="card-label">${c.label}</div>
      <div class="card-value ${c.cls}">${c.value}</div>
      <div class="card-sub">${c.sub}</div>
    </div>`
    )
    .join("");
}

// ─── Signal Table ─────────────────────────────────────────────────────────────
function renderSignalTable(trades) {
  const tbody = dom.signalTableBody();
  if (!tbody) return;

  if (!trades || !trades.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty-state">No buy signals found for this ticker with the current strategy.</td></tr>`;
    return;
  }

  tbody.innerHTML = trades
    .map((t) => {
      const exitBadge = t.is_active
        ? '<span class="badge badge-active">Active</span>'
        : t.exit_reason.includes("Stop")
        ? `<span class="badge badge-stoploss">${t.exit_reason}</span>`
        : '<span class="badge badge-closed">Closed</span>';

      const exitPrice = t.is_active
        ? `<span style="color:var(--text-muted);font-style:italic">${fmt(t.exit_price)}</span>`
        : `<span class="td-price">${fmt(t.exit_price)}</span>`;

      return `
      <tr>
        <td class="td-date">${t.signal_date}</td>
        <td class="td-ticker">${t.ticker}</td>
        <td><span class="badge badge-signal">MA200+RSI+MACD</span></td>
        <td class="td-price">${fmt(t.entry_price)}</td>
        <td>${exitPrice}</td>
        <td>${exitBadge}</td>
        <td class="td-days">${t.days_held}d</td>
        <td>${pnlSpan(t.gross_pnl_pct)}</td>
        <td>${pnlSpan(t.net_pnl_pct)}</td>
      </tr>`;
    })
    .join("");
}

// ─── Period Buttons ───────────────────────────────────────────────────────────
function initPeriodButtons() {
  document.querySelectorAll(".period-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".period-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.period = btn.dataset.period;
      loadStockData();
    });
  });
}

// ─── Cut-Loss Buttons ─────────────────────────────────────────────────────────
function initCutLossButtons() {
  document.querySelectorAll(".cl-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".cl-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const val = btn.dataset.cutloss;
      state.cutLoss = val === "none" ? null : parseFloat(val);
      if (state.activeTicker) loadBacktest(state.activeTicker);
    });
  });
}

// ─── Search ───────────────────────────────────────────────────────────────────
function initSearch() {
  const input = dom.searchInput();
  const dropdown = dom.searchDropdown();
  if (!input || !dropdown) return;

  let debounceTimer;

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      const q = input.value.trim();
      try {
        const res = await API.searchTickers(q);
        renderDropdown(res.results || []);
      } catch {}
    }, 250);
  });

  input.addEventListener("focus", () => {
    if (dropdown.children.length) dropdown.classList.add("visible");
  });

  document.addEventListener("click", (e) => {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.classList.remove("visible");
    }
  });

  // Add button
  const addBtn = document.getElementById("btn-add");
  if (addBtn) {
    addBtn.addEventListener("click", () => {
      const val = input.value.trim();
      if (val) {
        addTicker(val);
        input.value = "";
        dropdown.classList.remove("visible");
      }
    });
  }

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const val = input.value.trim();
      if (val) {
        addTicker(val);
        input.value = "";
        dropdown.classList.remove("visible");
      }
    }
  });
}

function renderDropdown(results) {
  const dropdown = dom.searchDropdown();
  if (!dropdown) return;
  dropdown.innerHTML = "";
  if (!results.length) {
    dropdown.classList.remove("visible");
    return;
  }
  results.forEach((ticker) => {
    const item = document.createElement("div");
    item.className = "search-item";
    item.textContent = ticker;
    item.addEventListener("click", () => {
      dom.searchInput().value = ticker;
      dropdown.classList.remove("visible");
      addTicker(ticker);
      dom.searchInput().value = "";
    });
    dropdown.appendChild(item);
  });
  dropdown.classList.add("visible");
}

// ─── Refresh Button ───────────────────────────────────────────────────────────
function initRefreshButton() {
  const btn = dom.refreshBtn();
  if (!btn) return;
  btn.addEventListener("click", async () => {
    if (!state.activeTicker) return;
    toast(`Refreshing ${state.activeTicker} from yfinance…`);
    try {
      await API.refreshStock(state.activeTicker);
      setTimeout(() => loadStockData(), 2000); // Give backend time to fetch
    } catch (e) {
      toast(`Refresh error: ${e.message}`, "error");
    }
  });
}

// ─── Tabs ─────────────────────────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const panel = tab.dataset.panel;
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      const panelEl = document.getElementById(panel);
      if (panelEl) panelEl.classList.add("active");
    });
  });
}

// ─── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  ChartManager.initCharts();
  initPeriodButtons();
  initCutLossButtons();
  initSearch();
  initRefreshButton();
  initTabs();
  await loadWatchlist();

  // Trigger initial search dropdown
  const res = await API.searchTickers("").catch(() => ({ results: [] }));
  renderDropdown(res.results || []);
}

window.addEventListener("load", init);
