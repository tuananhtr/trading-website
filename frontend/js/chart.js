/**
 * chart.js — TradingView Lightweight Charts integration.
 *
 * Architecture: single price chart (candles + MA200 + buy/sell signals).
 * MACD uses a second chart instance with logo hidden via CSS.
 */

let priceChart = null;
let candleSeries = null;
let ma200Series = null;
let macdChart = null;
let macdHistSeries = null;
let macdLineSeries = null;
let macdSignalSeries = null;

const CHART_OPTIONS = {
  layout: {
    background: { color: "#0b0e11" },
    textColor: "#8c94a1",
    fontSize: 11,
    fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
    attributionLogo: false,
  },
  grid: {
    vertLines: { color: "rgba(42,46,57,0.52)" },
    horzLines: { color: "rgba(42,46,57,0.52)" },
  },
  crosshair: {
    mode: 1,
    vertLine: { color: "rgba(100,116,139,0.4)", labelBackgroundColor: "#1c2536" },
    horzLine: { color: "rgba(100,116,139,0.4)", labelBackgroundColor: "#1c2536" },
  },
  rightPriceScale: {
    borderColor: "rgba(42,46,57,0.9)",
    scaleMargins: { top: 0.06, bottom: 0.06 },
  },
  timeScale: {
    borderColor: "rgba(42,46,57,0.9)",
    timeVisible: true,
    secondsVisible: false,
    rightOffset: 0,
    fixRightEdge: false,   // allow seeing the rightOffset gap
    fixLeftEdge: true,     // prevent scrolling past first data point
    tickMarkFormatter: (time) => {
      const d = new Date(time * 1000);
      return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
    },
  },
  handleScroll: true,
  handleScale:  true,
};

function initCharts() {
  const priceEl = document.getElementById("price-chart");
  const macdEl  = document.getElementById("macd-chart");

  if (!priceEl || typeof LightweightCharts === "undefined") return;

  // Clean up existing charts
  if (priceChart) { priceChart.remove(); priceChart = null; }
  if (macdChart)  { macdChart.remove();  macdChart  = null; }

  // ── Price Chart ──────────────────────────────────────────────────────
  priceChart = LightweightCharts.createChart(priceEl, {
    ...CHART_OPTIONS,
    width:  priceEl.clientWidth,
    height: priceEl.clientHeight,
  });

  // OHLC candles make the price view match a trading terminal and retain the
  // same marker API used by the strategy signals.
  candleSeries = priceChart.addCandlestickSeries({
    upColor:           "#22ab94",
    downColor:         "#f23645",
    borderUpColor:     "#22ab94",
    borderDownColor:   "#f23645",
    wickUpColor:       "#22ab94",
    wickDownColor:     "#f23645",
    priceLineVisible: false,
    lastValueVisible: true,
    crosshairMarkerVisible: true,
    crosshairMarkerRadius: 4,
    crosshairMarkerBorderColor: "#e9edf2",
    crosshairMarkerBackgroundColor: "#161a20",
  });

  // MA200 dashed overlay
  ma200Series = priceChart.addLineSeries({
    color:            "rgba(148,163,184,0.75)",
    lineWidth:        1.5,
    lineStyle:        1,
    title:            "MA200",
    priceLineVisible: false,
    lastValueVisible: true,
  });

  // ── MACD Chart ───────────────────────────────────────────────────────
  if (macdEl) {
    macdChart = LightweightCharts.createChart(macdEl, {
      ...CHART_OPTIONS,
      width:  macdEl.clientWidth,
      height: macdEl.clientHeight,
      layout: { ...CHART_OPTIONS.layout, attributionLogo: false },
      rightPriceScale: {
        borderColor:  "rgba(42,46,57,0.9)",
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: { ...CHART_OPTIONS.timeScale, visible: false },
    });

    macdHistSeries = macdChart.addHistogramSeries({
      priceLineVisible: false,
      lastValueVisible: false,
    });
    macdLineSeries = macdChart.addLineSeries({
      color: "#3b82f6", lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, title: "MACD",
    });
    macdSignalSeries = macdChart.addLineSeries({
      color: "#f59e0b", lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, title: "Signal",
    });

    // Sync time scales
    priceChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range && macdChart) macdChart.timeScale().setVisibleLogicalRange(range);
    });
    macdChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range && priceChart) priceChart.timeScale().setVisibleLogicalRange(range);
    });
  }

  // Resize observer
  const ro = new ResizeObserver(() => {
    if (priceChart) priceChart.resize(priceEl.clientWidth, priceEl.clientHeight);
    if (macdChart && macdEl) macdChart.resize(macdEl.clientWidth, macdEl.clientHeight);
  });
  ro.observe(priceEl);
  if (macdEl) ro.observe(macdEl);
}

function updateCharts(data) {
  if (!priceChart || !data) return;

  const { candles, ma200, signals, sell_signals } = data;

  // Candlestick series uses full OHLC bars supplied by the API.
  if (candles && candles.length) {
    candleSeries.setData(candles.map((c) => ({
      time: c.time, open: c.open, high: c.high, low: c.low, close: c.close,
    })));
  }

  if (ma200 && ma200.length) {
    ma200Series.setData(ma200);
  } else {
    ma200Series.setData([]);
  }

  // Signal markers appear on the confirmation bar; the trade table reports
  // the next bar's execution date. All markers must be sorted by time.
  const markers = (signals || []).map((s) => ({
    time:     s.time,
    position: "belowBar",
    color:    "#f59e0b",
    shape:    "arrowUp",
    text:     "BUY",
    size:     1.5,
  }));
  if (data.strategy === 2) {
    markers.push(...(sell_signals || []).map((s) => ({
      time: s.time,
      position: "aboveBar",
      color: "#4da6ff",
      shape: "arrowDown",
      text: "SELL",
      size: 1.5,
    })));
  }
  markers.sort((a, b) => a.time - b.time);
  candleSeries.setMarkers(markers);

  const sellLegend = document.getElementById("sell-signal-legend");
  if (sellLegend) sellLegend.hidden = data.strategy !== 2;

  // Set initial visible range to the selected period.
  // Right boundary = last candle + 3 days (avoids large empty gap on the right).
  const lastTs = (candles && candles.length > 0)
    ? candles[candles.length - 1].time
    : Math.floor(Date.now() / 1000);
  const fromTs = data.period_from_ts || 0;
  const toTs   = lastTs;   // no gap — last bar flush at right edge

  if (fromTs > 0) {
    priceChart.timeScale().setVisibleRange({ from: fromTs, to: toTs });
  } else {
    priceChart.timeScale().fitContent();  // ALL period — show everything
  }
  if (macdChart) macdChart.timeScale().fitContent();
}

function updateMacdChart(macdData) {
  if (!macdChart || !macdData) return;

  const histData = macdData
    .filter((d) => d.macd_hist != null)
    .map((d) => ({
      time:  d.time,
      value: d.macd_hist,
      color: d.macd_hist >= 0 ? "rgba(16,185,129,0.8)" : "rgba(239,68,68,0.8)",
    }));

  const lineData   = macdData.filter((d) => d.macd        != null).map((d) => ({ time: d.time, value: d.macd }));
  const signalData = macdData.filter((d) => d.macd_signal != null).map((d) => ({ time: d.time, value: d.macd_signal }));

  if (macdHistSeries)   macdHistSeries.setData(histData);
  if (macdLineSeries)   macdLineSeries.setData(lineData);
  if (macdSignalSeries) macdSignalSeries.setData(signalData);
  if (macdChart)        macdChart.timeScale().fitContent();
}

window.ChartManager = { initCharts, updateCharts, updateMacdChart };
