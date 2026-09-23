/**
 * chart.js — TradingView Lightweight Charts integration.
 *
 * Architecture: single price chart + volume as an overlay pane on the
 * same chart instance (so only ONE TradingView logo appears).
 * MACD uses a second chart instance but its logo is hidden via CSS.
 */

let priceChart = null;
let candleSeries = null;
let ma200Series = null;
let volumeSeries = null;   // lives inside priceChart, separate scale
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
    attributionLogo: false,   // hide TV logo where supported (v4.2+)
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
    scaleMargins: { top: 0.08, bottom: 0.22 },  // bottom margin reserved for volume bars
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
  handleScale: true,
};

function initCharts() {
  const priceEl = document.getElementById("price-chart");
  const macdEl  = document.getElementById("macd-chart");

  if (!priceEl || typeof LightweightCharts === "undefined") return;

  // Clean up existing charts
  if (priceChart) { priceChart.remove(); priceChart = null; }
  if (macdChart)  { macdChart.remove();  macdChart  = null; }

  // ── Price + Volume Chart (single instance) ──────────────────────────
  priceChart = LightweightCharts.createChart(priceEl, {
    ...CHART_OPTIONS,
    width:  priceEl.clientWidth,
    height: priceEl.clientHeight,
  });

  // Candlestick series
  candleSeries = priceChart.addCandlestickSeries({
    upColor:        "#10b981",
    downColor:      "#ef4444",
    borderUpColor:  "#10b981",
    borderDownColor:"#ef4444",
    wickUpColor:    "#10b981",
    wickDownColor:  "#ef4444",
  });

  // MA200 line overlay
  ma200Series = priceChart.addLineSeries({
    color:            "rgba(148,163,184,0.75)",
    lineWidth:        1.5,
    lineStyle:        1,        // dashed
    title:            "MA200",
    priceLineVisible: false,
    lastValueVisible: true,
  });

  // Volume histogram — uses a hidden separate price scale so it doesn't
  // interfere with the candle scale, and sits in the bottom 20% of the chart
  volumeSeries = priceChart.addHistogramSeries({
    priceFormat:      { type: "volume" },
    priceScaleId:     "vol",    // named scale, hidden on right
    lastValueVisible: false,
    priceLineVisible: false,
  });
  priceChart.priceScale("vol").applyOptions({
    scaleMargins: { top: 0.80, bottom: 0.00 },  // occupy bottom 20%
    visible: false,                              // hide the volume price axis
  });

  // ── MACD Chart (separate small chart below) ──────────────────────────
  if (macdEl) {
    macdChart = LightweightCharts.createChart(macdEl, {
      ...CHART_OPTIONS,
      width:  macdEl.clientWidth,
      height: macdEl.clientHeight,
      layout: {
        ...CHART_OPTIONS.layout,
        attributionLogo: false,
      },
      rightPriceScale: {
        borderColor:   "rgba(31,45,61,0.8)",
        scaleMargins:  { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        ...CHART_OPTIONS.timeScale,
        visible: false,   // time axis already shown on main chart
      },
    });

    macdHistSeries = macdChart.addHistogramSeries({
      priceLineVisible: false,
      lastValueVisible: false,
    });

    macdLineSeries = macdChart.addLineSeries({
      color:            "#3b82f6",
      lineWidth:        1.5,
      priceLineVisible: false,
      lastValueVisible: false,
      title:            "MACD",
    });

    macdSignalSeries = macdChart.addLineSeries({
      color:            "#f59e0b",
      lineWidth:        1.5,
      priceLineVisible: false,
      lastValueVisible: false,
      title:            "Signal",
    });

    // Sync MACD time scale with price chart (zoom/pan together)
    priceChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range && macdChart) macdChart.timeScale().setVisibleLogicalRange(range);
    });
    macdChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range && priceChart) priceChart.timeScale().setVisibleLogicalRange(range);
    });
  }

  // Resize observer — keeps charts filling their containers
  const ro = new ResizeObserver(() => {
    if (priceChart) priceChart.resize(priceEl.clientWidth, priceEl.clientHeight);
    if (macdChart && macdEl) macdChart.resize(macdEl.clientWidth, macdEl.clientHeight);
  });
  ro.observe(priceEl);
  if (macdEl) ro.observe(macdEl);
}

function updateCharts(data) {
  if (!priceChart || !data) return;

  const { candles, volumes, ma200, signals } = data;

  if (candles && candles.length) candleSeries.setData(candles);
  if (volumes && volumes.length) volumeSeries.setData(volumes);

  if (ma200 && ma200.length) {
    ma200Series.setData(ma200);
  } else {
    ma200Series.setData([]);
  }

  // Buy signal arrow markers
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
