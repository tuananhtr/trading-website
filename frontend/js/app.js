/**
 * app.js — Main application controller for the Vietnam Trading Dashboard.
 * Manages: watchlist, stock selection, chart rendering, backtest tables.
 */

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
  activeTicker: null,
  watchlist: [],
  period: "2Y",
  strategy: 1,       // 1 = Oversold Reversal, 2 = MACD Momentum
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
  performanceInsight: () => document.getElementById("performance-insight"),
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
  // The saved list is now used as the source for quick symbol loading.
  // It deliberately has no visible pill tray in the terminal layout.
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
    const data = await API.getStockData(ticker, state.period, state.strategy);
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
    const data = await API.getBacktest(ticker, state.cutLoss, state.period, state.strategy);
    state.backtestData = data;
    renderSummaryCards(data.summary);
    renderSignalTable(data.trades);
    // Update section title to show active period + strategy
    const titleEl = document.getElementById("backtest-title");
    const sLabel = state.strategy === 2 ? "S2 Momentum" : "S1 Oversold";
    if (titleEl) titleEl.textContent = `Buy Signals & Backtest — ${sLabel} — Last ${state.period}`;
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
  const insight = dom.performanceInsight();
  if (!container) return;
  if (!s || !Object.keys(s).length) {
    container.innerHTML = '<div class="empty-state"><div class="icon">📊</div>No backtest data yet</div>';
    if (insight) insight.innerHTML = "";
    return;
  }

  const signalPnl = s.total_net_pnl_pct ?? 0;
  const benchmarkReturn = s.benchmark_return_pct ?? 0;
  const benchmarkCagr = s.benchmark_cagr_pct ?? 0;
  const benchmarkDrawdown = s.benchmark_max_drawdown_pct ?? 0;
  const profitFactor = s.profit_factor == null ? "—" : s.profit_factor.toFixed(2);

  const cards = [
    { label: "Signal P&L*",          value: fmtPct(signalPnl),             sub: "Aggregate, not a portfolio", cls: signalPnl >= 0 ? "pos" : "neg" },
    { label: "Buy & Hold",           value: fmtPct(benchmarkReturn),        sub: "Same selected period",       cls: benchmarkReturn >= 0 ? "pos" : "neg" },
    { label: "Buy & Hold CAGR",      value: fmtPct(benchmarkCagr),          sub: "Annualised benchmark",       cls: benchmarkCagr >= 0 ? "pos" : "neg" },
    { label: "Benchmark Max DD",     value: fmtPct(benchmarkDrawdown),      sub: "Peak-to-trough decline",     cls: benchmarkDrawdown < 0 ? "neg" : "" },
    { label: "Median Signal P&L",    value: fmtPct(s.median_net_pnl_pct),   sub: "More robust than average",   cls: (s.median_net_pnl_pct ?? 0) >= 0 ? "pos" : "neg" },
    { label: "Profit Factor",        value: profitFactor,                   sub: s.profit_factor == null ? "No losing signals yet" : "Gross wins / gross losses", cls: s.profit_factor == null || s.profit_factor >= 1 ? "pos" : "neg" },
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

  if (insight) {
    const sampleWarning = (s.total_trades ?? 0) < 20
      ? '<span class="sample-warning">Small sample — interpret with care</span>'
      : '<span class="sample-ok">Meaningful signal sample</span>';
    insight.innerHTML = `
      <span><strong>${s.total_trades ?? 0}</strong> signals · <strong>${s.win_rate_pct ?? 0}%</strong> win rate</span>
      <span><strong>${s.active_trades ?? 0}</strong> active / ${s.closed_trades ?? 0} closed</span>
      <span>Median hold <strong>${s.median_hold_days ?? 0}d</strong></span>
      <span>Window: ${s.benchmark_start_date ?? "—"} → ${s.benchmark_end_date ?? "—"}</span>
      ${sampleWarning}
      <span class="performance-disclaimer">* Overlapping signals are not compounded into a portfolio return.</span>`;
  }
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
        <td><span class="badge badge-signal">${state.strategy === 2 ? "MACD>0+Cross" : "MA200+RSI+MACD"}</span></td>
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

// ─── Strategy Buttons ─────────────────────────────────────────────────────────
const STRATEGY_DESC = {
  1: "MA200 ↓ & RSI&lt;30 & MACD cross ↑",
  2: "MACD cross ↑ & MACD &gt; 0",
};

function initStrategyButtons() {
  const select = document.getElementById("strategy-select");
  if (!select) return;

  select.value = String(state.strategy);
  select.addEventListener("change", () => {
    const s = parseInt(select.value, 10);
    if (s === state.strategy) return;
    state.strategy = s;
    vn30Strategy = s;
    const descEl = document.getElementById("strategy-desc");
    if (descEl) descEl.innerHTML = STRATEGY_DESC[s] || "";
    if (state.activeTicker) loadStockData();
    loadVn30Ranking();
  });
}

// ─── VN30 Ranking ─────────────────────────────────────────────────────────────
let vn30Strategy = 1;  // active strategy in the VN30 sub-tab

async function loadVn30Ranking(forceRefresh = false) {
  const loading = document.getElementById("vn30-loading");
  const table   = document.getElementById("vn30-table");
  const empty   = document.getElementById("vn30-empty");

  loading.style.display = "block";
  table.style.display   = "none";
  empty.style.display   = "none";

  try {
    const data = await API.getVn30Ranking(vn30Strategy, forceRefresh);
    renderVn30Table(data);
  } catch (err) {
    loading.style.display = "none";
    empty.style.display   = "block";
    empty.querySelector("div:last-child").textContent = "Error: " + err.message;
    toast("VN30 load failed: " + err.message, "error");
  }
}

function renderVn30Table(data) {
  const loading = document.getElementById("vn30-loading");
  const table   = document.getElementById("vn30-table");
  const empty   = document.getElementById("vn30-empty");
  const body    = document.getElementById("vn30-table-body");
  const updated = document.getElementById("vn30-updated");

  loading.style.display = "none";

  if (!data.results || data.results.length === 0) {
    empty.style.display = "block";
    return;
  }

  // Format updated_at
  if (data.updated_at) {
    const d = new Date(data.updated_at);
    updated.textContent = `Updated: ${d.toLocaleString("en-GB", { day:"2-digit", month:"short", hour:"2-digit", minute:"2-digit" })}`;
  }

  body.innerHTML = data.results.map((r) => {
    const rankCell = r.rank
      ? `<td style="font-weight:700;color:${r.rank<=3?"var(--amber)":"var(--text-muted)"};">${r.rank}</td>`
      : `<td style="color:var(--text-muted);">—</td>`;

    const price = r.last_close != null
      ? Number(r.last_close).toLocaleString("en-US")
      : "—";

    if (r.total_trades === 0 || r.status !== "ok") {
      return `<tr style="opacity:0.45;">
        ${rankCell}
        <td class="td-ticker">${r.ticker}</td>
        <td>${price}</td>
        <td style="color:var(--text-muted);">—</td>
        <td>—</td>
        <td>—</td>
      </tr>`;
    }

    const avgPnl  = r.avg_net_pnl_pct ?? 0;
    const best    = r.best_trade_pct ?? 0;
    const wr      = r.win_rate_pct ?? 0;
    const hold    = r.avg_hold_days ?? 0;

    const pnlClr  = (v) => v >= 0 ? "var(--green)" : "var(--red)";
    const pnlFmt  = (v) => `${v >= 0 ? "▲" : "▼"} ${Math.abs(v).toFixed(2)}%`;

    return `<tr>
      ${rankCell}
      <td class="td-ticker">${r.ticker}</td>
      <td class="td-price">${price}</td>
      <td style="color:${pnlClr(avgPnl)};font-weight:700;">${pnlFmt(avgPnl)}</td>
      <td>${wr.toFixed(0)}%</td>
      <td>${r.total_trades}</td>
    </tr>`;
  }).join("");

  table.style.display = "";
  empty.style.display = "none";
}

function initVn30Tab() {
  const refreshBtn = document.getElementById("vn30-refresh-btn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", async () => {
      refreshBtn.disabled = true;
      refreshBtn.textContent = "⏳ Refreshing…";
      toast("Downloading VN30 prices in background…", "info");
      try {
        await API.refreshVn30();
        toast("VN30 data refresh started (takes ~2 min)", "success");
        // After a delay, reload ranking with fresh data
        setTimeout(() => loadVn30Ranking(true), 5000);
      } catch (e) {
        toast("Refresh failed: " + e.message, "error");
      } finally {
        setTimeout(() => {
          refreshBtn.disabled = false;
          refreshBtn.textContent = "🔄 Refresh";
        }, 5000);
      }
    });
  }

  // The ranking is a persistent right-hand market scanner, not a hidden tab.
  loadVn30Ranking();
}

// ─── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  ChartManager.initCharts();
  initPeriodButtons();
  initCutLossButtons();
  initStrategyButtons();
  initVn30Tab();
  initSearch();
  initRefreshButton();
  initTabs();
  await loadWatchlist();
}

window.addEventListener("load", init);
