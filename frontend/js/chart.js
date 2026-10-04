/**
 * chart.js — TradingView Lightweight Charts integration.
 *
 * Architecture: single price chart (area line + MA200 + buy signals).
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
    background: { color: "#161d2a" },
    textColor: "#64748b",
    fontSize: 11,
    fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
    attributionLogo: false,
  },
  grid: {
    vertLines: { color: "rgba(31,45,61,0.5)" },
    horzLines: { color: "rgba(31,45,61,0.5)" },
  },
  crosshair: {
    mode: 1,
    vertLine: { color: "rgba(100,116,139,0.4)", labelBackgroundColor: "#1c2536" },
    horzLine: { color: "rgba(100,116,139,0.4)", labelBackgroundColor: "#1c2536" },
  },
  rightPriceScale: {
    borderColor: "rgba(31,45,61,0.8)",
    scaleMargins: { top: 0.06, bottom: 0.06 },  // full height now — no volume
  },
  timeScale: {
    borderColor: "rgba(31,45,61,0.8)",
    timeVisible: true,
    secondsVisible: false,
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

  // Area / line series
  candleSeries = priceChart.addAreaSeries({
    lineColor:        "#3b82f6",
    topColor:         "rgba(59,130,246,0.18)",
    bottomColor:      "rgba(59,130,246,0.00)",
    lineWidth:        2,
    priceLineVisible: false,
    lastValueVisible: true,
    crosshairMarkerVisible: true,
    crosshairMarkerRadius: 4,
    crosshairMarkerBorderColor: "#3b82f6",
    crosshairMarkerBackgroundColor: "#1e3a5f",
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
        borderColor:  "rgba(31,45,61,0.8)",
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

  const { candles, ma200, signals } = data;

  // Area series uses {time, value} (close price)
  if (candles && candles.length) {
    candleSeries.setData(candles.map((c) => ({ time: c.time, value: c.close })));
  }

  if (ma200 && ma200.length) {
    ma200Series.setData(ma200);
  } else {
    ma200Series.setData([]);
  }

  // Buy signal markers
  const markers = (signals || []).map((s) => ({
    time:     s.time,
    position: "belowBar",
    color:    "#f59e0b",
    shape:    "arrowUp",
    text:     "BUY",
    size:     1.5,
  }));
  candleSeries.setMarkers(markers);

  priceChart.timeScale().fitContent();
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
