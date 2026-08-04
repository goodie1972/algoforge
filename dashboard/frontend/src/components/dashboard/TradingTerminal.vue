<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
let autoScrollTimer: ReturnType<typeof setTimeout> | null = null
let autoScrollScheduled = false
function scheduleAutoScroll() {
  if (autoScrollScheduled) return  // 防止 scrollAllToRealTime 触发的事件循环
  if (autoScrollTimer) clearTimeout(autoScrollTimer)
  autoScrollTimer = setTimeout(() => {
    autoScrollScheduled = true
    scrollAllToRealTime()
    setTimeout(() => { autoScrollScheduled = false }, 500)
  }, 10000)
}
import { usePriceStore } from '@/stores/prices'
import { useFlashOnChange } from '@/composables/useFlashOnChange'
import { createChart, ColorType, type UTCTimestamp } from 'lightweight-charts'
import {
  calcEMA, calcSMA, calcBollinger, calcRSI, calcStoch,
  calcMACD, calcATR, calcVolume,
  type CandleData, type LinePoint, type BandPoint, type HistogramPoint,
} from '@/utils/indicators'

function sanitizeCandleData(candles: CandleData[]) {
  return candles
    .filter(c => c.open != null && c.high != null && c.low != null && c.close != null)
    .map(c => ({
      time: c.time as UTCTimestamp,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }))
}

const store = usePriceStore()
const chartContainer = ref<HTMLDivElement>()

// 副图容器 refs
const rsiRef = ref<HTMLDivElement>()
const stochRef = ref<HTMLDivElement>()
const macdRef = ref<HTMLDivElement>()
const atrRef = ref<HTMLDivElement>()
const volRef = ref<HTMLDivElement>()

function getPaneEl(name: string): HTMLDivElement | undefined {
  const map: Record<string, any> = { rsi: rsiRef, stoch: stochRef, macd: macdRef, atr: atrRef, volume: volRef }
  return map[name]?.value
}

function castTime<T extends { time: number }>(arr: T[]): (T & { time: UTCTimestamp })[] {
  return arr.map(p => ({ ...p, time: p.time as UTCTimestamp }))
}

let chart: ReturnType<typeof createChart> | null = null
let candleSeries: any = null
let overlaySeries: Record<string, any> = {}

// 副图实例（按 oscillator name）
let paneCharts: Record<string, ReturnType<typeof createChart>> = {}
let paneSeries: Record<string, any> = {}

const timeframes = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1']
const activeTf = ref('H1')
let refreshTimer: ReturnType<typeof setInterval> | null = null

// ---- localStorage 持久化（保存周期和指标配置） ----
const STORAGE_KEY = 'algoforge_terminal_config'
function loadTerminalConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const cfg = JSON.parse(raw)
    activeTf.value = cfg.tf || 'H1'
    showEMA.value = cfg.showEMA ?? false
    showSMA.value = cfg.showSMA ?? false
    showBB.value = cfg.showBB ?? false
    showRSI.value = cfg.showRSI ?? false
    showStoch.value = cfg.showStoch ?? false
    showMACD.value = cfg.showMACD ?? false
    showATR.value = cfg.showATR ?? false
    showVolume.value = cfg.showVolume ?? false
    if (cfg.emaPeriods) emaPeriods.value = cfg.emaPeriods
    if (cfg.smaPeriods) smaPeriods.value = cfg.smaPeriods
    if (cfg.bbPeriod) bbPeriod.value = cfg.bbPeriod
    if (cfg.bbStd) bbStd.value = cfg.bbStd
    if (cfg.rsiPeriod) rsiPeriod.value = cfg.rsiPeriod
    if (cfg.rsiOb) rsiOb.value = cfg.rsiOb
    if (cfg.rsiOs) rsiOs.value = cfg.rsiOs
    if (cfg.stochK) stochK.value = cfg.stochK
    if (cfg.stochKSmooth) stochKSmooth.value = cfg.stochKSmooth
    if (cfg.stochDSmooth) stochDSmooth.value = cfg.stochDSmooth
    if (cfg.macdFast) macdFast.value = cfg.macdFast
    if (cfg.macdSlow) macdSlow.value = cfg.macdSlow
    if (cfg.macdSignal) macdSignal.value = cfg.macdSignal
    if (cfg.atrPeriod) atrPeriod.value = cfg.atrPeriod
  } catch (e) { /* ignore corrupt config */ }
}
function saveTerminalConfig() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      tf: activeTf.value,
      showEMA: showEMA.value, showSMA: showSMA.value, showBB: showBB.value,
      showRSI: showRSI.value, showStoch: showStoch.value, showMACD: showMACD.value,
      showATR: showATR.value, showVolume: showVolume.value,
      emaPeriods: emaPeriods.value, smaPeriods: smaPeriods.value,
      bbPeriod: bbPeriod.value, bbStd: bbStd.value,
      rsiPeriod: rsiPeriod.value, rsiOb: rsiOb.value, rsiOs: rsiOs.value,
      stochK: stochK.value, stochKSmooth: stochKSmooth.value, stochDSmooth: stochDSmooth.value,
      macdFast: macdFast.value, macdSlow: macdSlow.value, macdSignal: macdSignal.value,
      atrPeriod: atrPeriod.value,
    }))
  } catch (e) { /* ignore storage error */ }
}

// 各周期默认指标预设 — 切换周期时自动启用/停用
const tfIndicatorPresets: Record<string, Record<string, boolean>> = {
  M5:  { rsi: false, stoch: false, macd: false, bb: true,  volume: true  },
  M15: { rsi: false, stoch: false, macd: false, bb: true,  volume: false },
  M30: { rsi: false, stoch: false, macd: true,  bb: true,  volume: false },
  H1:  { rsi: true,  stoch: false, macd: false, bb: true,  volume: false },
  H4:  { rsi: false, stoch: true,  macd: false, bb: true,  volume: false },
  D1:  { rsi: false, stoch: false, macd: false, bb: false, volume: false },
  W1:  { rsi: false, stoch: false, macd: false, bb: false, volume: false },
}

function getRefreshInterval(tf: string): number {
  if (tf === 'M1' || tf === 'M5' || tf === 'M15') return 2_000
  if (tf === 'M30' || tf === 'H1') return 2_000
  if (tf === 'H4') return 10_000
  return 30_000 // D1, W1
}

function stopAutoRefresh() {
  if (refreshTimer !== null) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  const ms = getRefreshInterval(activeTf.value)
  refreshTimer = setInterval(async () => {
    if (!candleSeries) return
    // 只拉最新 3 根增量更新，不触发 loading 转圈
    await store.fetchLatestCandles(activeTf.value, 3)
    if (store.candles.length === 0) return
    try { candleSeries.setData(sanitizeCandleData(store.candles)) }
    catch (e) { console.warn('[K线] auto-refresh setData失败', e) }
    afterDataLoad()
    nextTick(() => {
      scrollAllToRealTime()
      requestAnimationFrame(() => syncAllPriceScaleWidths())
    })
  }, ms)
}

// 指标开关
const showEMA = ref(false)
const showSMA = ref(false)
const showBB = ref(false)
const showRSI = ref(false)
const showStoch = ref(false)
const showMACD = ref(false)
const showATR = ref(false)
const showVolume = ref(false)

// 指标参数
const emaPeriods = ref('20,50,200')
const smaPeriods = ref('20,50')
const bbPeriod = ref(20)
const bbStd = ref(2)
const rsiPeriod = ref(14)
const rsiOb = ref(70)
const rsiOs = ref(30)
const stochK = ref(14)
const stochKSmooth = ref(3)
const stochDSmooth = ref(3)
const macdFast = ref(12)
const macdSlow = ref(26)
const macdSignal = ref(9)
const atrPeriod = ref(14)

function parsePeriods(s: string): number[] {
  return s.split(',').map(n => parseInt(n.trim())).filter(n => !isNaN(n) && n > 0)
}

// 参数变更时重建对应指标
watch([showEMA, showSMA, showBB, emaPeriods, smaPeriods, bbPeriod, bbStd], () => {
  applyOverlay()
  saveTerminalConfig()
})
// 复选框切换时重建/销毁副图
watch(showRSI, () => { destroyPane('rsi'); if (showRSI.value) applyRSI(); saveTerminalConfig() })
watch(showStoch, () => { destroyPane('stoch'); if (showStoch.value) applyStoch(); saveTerminalConfig() })
watch(showMACD, () => { destroyPane('macd'); if (showMACD.value) applyMACD(); saveTerminalConfig() })
watch(showATR, () => { destroyPane('atr'); if (showATR.value) applyATR(); saveTerminalConfig() })
watch(showVolume, () => { destroyPane('volume'); if (showVolume.value) applyVolume(); saveTerminalConfig() })

// 参数数值变更时刷新副图（代替无效的 @update:value="{...}" 语法）
function refreshRSI() { destroyPane('rsi'); if (showRSI.value) applyRSI(); saveTerminalConfig() }
function refreshStoch() { destroyPane('stoch'); if (showStoch.value) applyStoch(); saveTerminalConfig() }
function refreshMACD() { destroyPane('macd'); if (showMACD.value) applyMACD(); saveTerminalConfig() }
function refreshATR() { destroyPane('atr'); if (showATR.value) applyATR(); saveTerminalConfig() }

const chartHeight = 420
const paneHeight = 110

// 双向时间轴同步：任意图缩放时所有图一同缩放
let _syncLock = false
function syncAllChartsFrom(source: any) {
  if (_syncLock) return
  _syncLock = true
  const range = source.timeScale().getVisibleLogicalRange()
  if (range) {
    // 双向同步：不论主图还是副图，所有图同步缩放/拖拽
    if (source !== chart) {
      chart?.timeScale().setVisibleLogicalRange(range)
    }
    for (const pc of Object.values(paneCharts)) {
      if (pc !== source) pc.timeScale().setVisibleLogicalRange(range)
    }
  }
  _syncLock = false
}

function makeChartOptions(width: number, height: number, showTimeScale: boolean): any {
  return {
    layout: {
      background: { type: ColorType.Solid, color: '#1a1d23' },
      textColor: '#8b8f97',
    },
    grid: {
      vertLines: { color: '#2d3139' },
      horzLines: { color: '#2d3139' },
    },
    width,
    height,
    timeScale: {
      timeVisible: false,
      borderColor: '#2d3139',
      visible: showTimeScale,
    },
    rightPriceScale: { borderColor: '#2d3139' },
    crosshair: { mode: 0 },
  }
}

onMounted(() => {
  if (!chartContainer.value) return
  const w = chartContainer.value.clientWidth

  chart = createChart(chartContainer.value, makeChartOptions(w, chartHeight, true))

  candleSeries = chart.addCandlestickSeries({
    upColor: '#0ecb81',
    downColor: '#f6465d',
    borderUpColor: '#0ecb81',
    borderDownColor: '#f6465d',
    wickUpColor: '#0ecb81',
    wickDownColor: '#f6465d',
  })

  // 先应用周期预设，再加载保存的配置覆盖（让保存的配置优先）
  applyTfPreset()
  loadTerminalConfig()
  loadCandles()

  const observer = new ResizeObserver(() => {
    if (chart && chartContainer.value) {
      const nw = chartContainer.value.clientWidth
      chart.applyOptions({ width: nw })
      Object.values(paneCharts).forEach(pc => pc.applyOptions({ width: nw }))
      requestAnimationFrame(() => syncAllPriceScaleWidths())
    }
  })
  observer.observe(chartContainer.value)

  // 双向时间轴同步：主图缩放 → 所有副图
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    syncAllChartsFrom(chart!)
    scheduleAutoScroll()
  })
  chart.subscribeCrosshairMove(() => {
    syncAllChartsFrom(chart!)
    scheduleAutoScroll()
  })

  startAutoRefresh()
})

onUnmounted(() => {
  stopAutoRefresh()
  chart?.remove()
  Object.values(paneCharts).forEach(pc => pc.remove())
})

// 数值闪烁 — 内联实现，直接 watch store
const bidFlash = ref(false)
let _bTimer: any = null
let _bLast = store.bid
watch(() => store.bid, (n) => {
  if (Math.abs(n - _bLast) < 0.01) return
  _bLast = n
  bidFlash.value = true
  if (_bTimer) clearTimeout(_bTimer)
  _bTimer = setTimeout(() => { bidFlash.value = false }, 600)
})

const askFlash = ref(false)
let _aTimer: any = null
let _aLast = store.ask
watch(() => store.ask, (n) => {
  if (Math.abs(n - _aLast) < 0.01) return
  _aLast = n
  askFlash.value = true
  if (_aTimer) clearTimeout(_aTimer)
  _aTimer = setTimeout(() => { askFlash.value = false }, 600)
})

const spreadFlash = ref(false)
let _sTimer: any = null
let _sLast = store.spread
watch(() => store.spread, (n) => {
  if (Math.abs(n - _sLast) < 0.01) return
  _sLast = n
  spreadFlash.value = true
  if (_sTimer) clearTimeout(_sTimer)
  _sTimer = setTimeout(() => { spreadFlash.value = false }, 600)
})

// K 线实时跳动：WebSocket tick 驱动 candleSeries.update() 更新最后一根
// 时间戳偏移已修复，update 时间戳与缓存数据一致

let _lastMid = -1
watch([() => store.bid, () => store.ask], ([bid, ask]) => {
  if (!candleSeries || bid <= 0 || ask <= 0) return
  const mid = (bid + ask) / 2
  if (Math.abs(mid - _lastMid) < 0.01) return
  _lastMid = mid
  const lastCandle = store.candles[store.candles.length - 1]
  if (!lastCandle) return
  try {
    candleSeries.update({
      time: lastCandle.time as UTCTimestamp,
      open: lastCandle.open,
      high: Math.max(lastCandle.high, mid),
      low: Math.min(lastCandle.low, mid),
      close: mid,
    })
  } catch (e) { /* ignore */ }
})

function getCandleData(): CandleData[] {
  return store.candles.map(c => ({
    time: c.time,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
    volume: (c as any).volume || 0,
  }))
}

// 将指标数据填充 NaN 补齐到与 K 线等长，确保主图和副图数据点数量一致
function padLinePoints(candles: CandleData[], points: LinePoint[]): LinePoint[] {
  const map = new Map(points.map(p => [p.time, p.value]))
  return candles.map(c => ({ time: c.time, value: map.get(c.time) ?? NaN }))
}
function padBandPoints(candles: CandleData[], points: BandPoint[], field: 'upper' | 'middle' | 'lower'): LinePoint[] {
  const map = new Map(points.map(p => [p.time, p[field]]))
  return candles.map(c => ({ time: c.time, value: map.get(c.time) ?? NaN }))
}
function padHistogram(candles: CandleData[], points: HistogramPoint[]): HistogramPoint[] {
  const map = new Map(points.map(p => [p.time, p]))
  return candles.map(c => map.get(c.time) ?? { time: c.time, value: NaN })
}

// ---- 主图叠加指标 ----
function applyOverlay() {
  const data = getCandleData()
  if (!chart || data.length === 0) return

  // EMA
  const emaColors = ['#f0b90b', '#e88b37', '#ef3b6d', '#0ecb81', '#8b8f97']
  if (showEMA.value) {
    const periods = parsePeriods(emaPeriods.value)
    periods.forEach((p, i) => {
      const key = `ema${p}`
      ensureOverlaySeries(key, { color: emaColors[i % emaColors.length], lineWidth: 1 })
      overlaySeries[key].setData(castTime(padLinePoints(data, calcEMA(data, p))))
    })
  }
  // 清理不在参数列表中的 EMA 系列（取消勾选时全部清理）
  const emaKeys = showEMA.value ? parsePeriods(emaPeriods.value).map(p => `ema${p}`) : []
  Object.keys(overlaySeries).forEach(k => {
    if (k.startsWith('ema') && !emaKeys.includes(k)) removeOverlaySeries(k)
  })

  // SMA
  const smaColors = ['#0ecb81', '#f6465d', '#f0b90b', '#e88b37', '#8b8f97']
  if (showSMA.value) {
    const periods = parsePeriods(smaPeriods.value)
    periods.forEach((p, i) => {
      const key = `sma${p}`
      ensureOverlaySeries(key, { color: smaColors[i % smaColors.length], lineWidth: 1, lineStyle: 2 })
      overlaySeries[key].setData(castTime(padLinePoints(data, calcSMA(data, p))))
    })
  }
  const smaKeys = showSMA.value ? parsePeriods(smaPeriods.value).map(p => `sma${p}`) : []
  Object.keys(overlaySeries).forEach(k => {
    if (k.startsWith('sma') && !smaKeys.includes(k)) removeOverlaySeries(k)
  })

  // Bollinger Bands
  if (showBB.value) {
    const bb = calcBollinger(data, bbPeriod.value, bbStd.value)
    ensureOverlaySeries('bb_upper', { color: '#8b8f97', lineWidth: 1, lineStyle: 2 })
    ensureOverlaySeries('bb_middle', { color: '#f0b90b', lineWidth: 1 })
    ensureOverlaySeries('bb_lower', { color: '#8b8f97', lineWidth: 1, lineStyle: 2 })
    overlaySeries['bb_upper'].setData(castTime(padBandPoints(data, bb, 'upper')))
    overlaySeries['bb_middle'].setData(castTime(padBandPoints(data, bb, 'middle')))
    overlaySeries['bb_lower'].setData(castTime(padBandPoints(data, bb, 'lower')))
  } else {
    removeOverlaySeries('bb_upper')
    removeOverlaySeries('bb_middle')
    removeOverlaySeries('bb_lower')
  }
}

function ensureOverlaySeries(key: string, opts: any) {
  if (!chart || overlaySeries[key]) return
  overlaySeries[key] = chart.addLineSeries({
    color: opts.color,
    lineWidth: opts.lineWidth || 1,
    lineStyle: opts.lineStyle || 0,
    priceLineVisible: false,
    lastValueVisible: false,
  })
}

function removeOverlaySeries(key: string) {
  if (!chart || !overlaySeries[key]) return
  chart.removeSeries(overlaySeries[key])
  delete overlaySeries[key]
}

// ---- 副图 ----
function destroyPane(name: string) {
  const pc = paneCharts[name]
  if (pc) { pc.remove(); delete paneCharts[name] }
  delete paneSeries[name]
}

function applyRSI() {
  if (!showRSI.value) { destroyPane('rsi'); return }
  const data = getCandleData()
  if (data.length === 0) return
  const rsiData = padLinePoints(data, calcRSI(data, rsiPeriod.value))

  nextTick(() => {
    const container = getPaneEl('rsi')
    if (!container || !chart) return
    const w = chartContainer.value!.clientWidth

    let pc = paneCharts['rsi']
    if (!pc) {
      pc = createChart(container, makeChartOptions(w, paneHeight, false))
      paneCharts['rsi'] = pc
      pc.timeScale().subscribeVisibleLogicalRangeChange(() => { syncAllChartsFrom(pc) })
    }

    if (!paneSeries['rsi']) {
      const series = pc.addLineSeries({
        color: '#f0b90b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      })
      const overbought = pc.addLineSeries({
        color: '#f6465d', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      })
      const oversold = pc.addLineSeries({
        color: '#0ecb81', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      })
      overbought.setData(castTime(data.map(c => ({ time: c.time, value: rsiOb.value }))))
      oversold.setData(castTime(data.map(c => ({ time: c.time, value: rsiOs.value }))))
      paneSeries['rsi'] = { series, overbought, oversold }
      pc.priceScale('right').applyOptions({ scaleMargins: { top: 0.05, bottom: 0.05 } })
    }

    paneSeries['rsi'].series.setData(castTime(rsiData))
    syncPaneRange('rsi')
    requestAnimationFrame(() => syncAllPriceScaleWidths())
  })
}

function applyStoch() {
  if (!showStoch.value) { destroyPane('stoch'); return }
  const data = getCandleData()
  if (data.length === 0) return
  const stoch = calcStoch(data, stochK.value, stochKSmooth.value, stochDSmooth.value)
  const stochKData = padLinePoints(data, stoch.k)
  const stochDData = padLinePoints(data, stoch.d)

  nextTick(() => {
    const container = getPaneEl('stoch')
    if (!container || !chart) return
    const w = chartContainer.value!.clientWidth

    let pc = paneCharts['stoch']
    if (!pc) {
      pc = createChart(container, makeChartOptions(w, paneHeight, false))
      paneCharts['stoch'] = pc
      pc.timeScale().subscribeVisibleLogicalRangeChange(() => { syncAllChartsFrom(pc) })
    }

    if (!paneSeries['stoch']) {
      const kSeries = pc.addLineSeries({
        color: '#f0b90b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      })
      const dSeries = pc.addLineSeries({
        color: '#e88b37', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      })
      paneSeries['stoch'] = { k: kSeries, d: dSeries }
    }

    paneSeries['stoch'].k.setData(castTime(stochKData))
    paneSeries['stoch'].d.setData(castTime(stochDData))
    syncPaneRange('stoch')
    requestAnimationFrame(() => syncAllPriceScaleWidths())
  })
}

function applyMACD() {
  if (!showMACD.value) { destroyPane('macd'); return }
  const data = getCandleData()
  if (data.length === 0) return
  const macd = calcMACD(data, macdFast.value, macdSlow.value, macdSignal.value)
  const macdLineData = padLinePoints(data, macd.macd)
  const signalData = padLinePoints(data, macd.signal)
  const histData = padHistogram(data, macd.histogram)

  nextTick(() => {
    const container = getPaneEl('macd')
    if (!container || !chart) return
    const w = chartContainer.value!.clientWidth

    let pc = paneCharts['macd']
    if (!pc) {
      pc = createChart(container, makeChartOptions(w, paneHeight, false))
      paneCharts['macd'] = pc
      pc.timeScale().subscribeVisibleLogicalRangeChange(() => { syncAllChartsFrom(pc) })
    }

    if (!paneSeries['macd']) {
      const macdSeries = pc.addLineSeries({
        color: '#f0b90b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      })
      const signalSeries = pc.addLineSeries({
        color: '#e88b37', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      })
      const histSeries = pc.addHistogramSeries({
        priceLineVisible: false, lastValueVisible: false,
      })
      paneSeries['macd'] = { macd: macdSeries, signal: signalSeries, histogram: histSeries }
    }

    paneSeries['macd'].macd.setData(castTime(macdLineData))
    paneSeries['macd'].signal.setData(castTime(signalData))
    paneSeries['macd'].histogram.setData(castTime(histData))
    syncPaneRange('macd')
    requestAnimationFrame(() => syncAllPriceScaleWidths())
  })
}

function applyATR() {
  if (!showATR.value) { destroyPane('atr'); return }
  const data = getCandleData()
  if (data.length === 0) return
  const atrData = padLinePoints(data, calcATR(data, atrPeriod.value))

  nextTick(() => {
    const container = getPaneEl('atr')
    if (!container || !chart) return
    const w = chartContainer.value!.clientWidth

    let pc = paneCharts['atr']
    if (!pc) {
      pc = createChart(container, makeChartOptions(w, paneHeight, false))
      paneCharts['atr'] = pc
      pc.timeScale().subscribeVisibleLogicalRangeChange(() => { syncAllChartsFrom(pc) })
    }

    if (!paneSeries['atr']) {
      paneSeries['atr'] = pc.addLineSeries({
        color: '#0ecb81', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      })
    }

    paneSeries['atr'].setData(castTime(atrData))
    syncPaneRange('atr')
    requestAnimationFrame(() => syncAllPriceScaleWidths())
  })
}

function applyVolume() {
  if (!showVolume.value) { destroyPane('volume'); return }
  const data = getCandleData()
  if (data.length === 0) return
  const vol = calcVolume(data)

  nextTick(() => {
    const container = getPaneEl('volume')
    if (!container || !chart) return
    const w = chartContainer.value!.clientWidth

    let pc = paneCharts['volume']
    if (!pc) {
      pc = createChart(container, makeChartOptions(w, paneHeight, false))
      paneCharts['volume'] = pc
      pc.timeScale().subscribeVisibleLogicalRangeChange(() => { syncAllChartsFrom(pc) })
    }

    if (!paneSeries['volume']) {
      paneSeries['volume'] = pc.addHistogramSeries({
        priceLineVisible: false, lastValueVisible: false,
      })
    }

    paneSeries['volume'].setData(castTime(vol))
    syncPaneRange('volume')
    requestAnimationFrame(() => syncAllPriceScaleWidths())
  })
}

function syncPriceScaleWidth(name: string) {
  const pc = paneCharts[name]
  if (!pc || !chart) return
  const target = chart.priceScale('right').width()
  if (target > 0) {
    pc.priceScale('right').applyOptions({ minimumWidth: target })
  }
}

function syncPaneRange(name: string) {
  const pc = paneCharts[name]
  if (!pc || !chart) return
  const range = chart.timeScale().getVisibleLogicalRange()
  if (range) pc.timeScale().setVisibleLogicalRange(range)
}

function syncAllPanes() {
  if (!chart) return
  for (const name of Object.keys(paneCharts)) {
    syncPaneRange(name)
  }
}

function scrollAllToRealTime() {
  chart?.timeScale().scrollToRealTime()
  Object.values(paneCharts).forEach(pc => pc.timeScale().scrollToRealTime())
}

function syncAllPriceScaleWidths() {
  if (!chart) return
  const mainWidth = chart.priceScale('right').width()
  if (mainWidth <= 0) return
  for (const name of Object.keys(paneCharts)) {
    paneCharts[name].priceScale('right').applyOptions({ minimumWidth: mainWidth })
  }
}

// ---- 数据加载 ----
async function loadCandles() {
  await store.fetchCandles(activeTf.value, 500)
  if (candleSeries && store.candles.length > 0) {
    try { candleSeries.setData(sanitizeCandleData(store.candles)) }
  catch (e) { console.warn('[K线] setData失败', e) }
    // 先计算所有指标（异步创建副图）
    afterDataLoad()
    // 等所有副图创建完毕后，统一右对齐所有图表
    nextTick(() => {
      scrollAllToRealTime()
      // 等主图渲染完毕后，统一副图价格刻度宽度（使 K 线区域右对齐）
      requestAnimationFrame(() => syncAllPriceScaleWidths())
    })
  }
}

function afterDataLoad() {
  applyOverlay()
  applyRSI()
  applyStoch()
  applyMACD()
  applyATR()
  applyVolume()
}

/** 根据当前周期应用预设指标 */
function applyTfPreset() {
  const preset = tfIndicatorPresets[activeTf.value]
  if (!preset) return
  showRSI.value = preset.rsi ?? false
  showStoch.value = preset.stoch ?? false
  showMACD.value = preset.macd ?? false
  showBB.value = preset.bb ?? false
  showVolume.value = preset.volume ?? false
  showEMA.value = false
  showSMA.value = false
  showATR.value = false
}

async function switchTf(tf: string) {
  activeTf.value = tf
  stopAutoRefresh()
  clearAllOverlays()
  clearAllPanes()
  applyTfPreset()
  await loadCandles()
  startAutoRefresh()
  saveTerminalConfig()
}

function clearAllOverlays() {
  if (!chart) return
  Object.keys(overlaySeries).forEach(k => {
    chart!.removeSeries(overlaySeries[k])
    delete overlaySeries[k]
  })
}

function clearAllPanes() {
  Object.keys(paneCharts).forEach(k => {
    paneCharts[k].remove()
    delete paneCharts[k]
    delete paneSeries[k]
  })
}

</script>

<template>
  <n-card :title="$t('terminal.title')" size="small">
    <template #header-extra>
      <n-space size="small">
        <n-button v-for="tf in timeframes" :key="tf" size="tiny"
                  :type="activeTf === tf ? 'primary' : 'default'"
                  @click="switchTf(tf)">
          {{ tf }}
        </n-button>
      </n-space>
    </template>

    <!-- 实时价格栏 -->
    <n-grid :cols="4" :x-gap="16" style="margin-bottom: 6px;">
      <n-gi><n-text depth="3" style="font-size:12px;">{{ $t('terminal.bid') }}</n-text> <span class="price-up" :class="{ 'flash-num': bidFlash }" style="font-size:13px;display:inline-block;padding:1px 4px;border-radius:3px;transition:background .15s;"><strong>{{ store.bid.toFixed(2) }}</strong></span></n-gi>
      <n-gi><n-text depth="3" style="font-size:12px;">{{ $t('terminal.ask') }}</n-text> <span class="price-down" :class="{ 'flash-num': askFlash }" style="font-size:13px;display:inline-block;padding:1px 4px;border-radius:3px;transition:background .15s;"><strong>{{ store.ask.toFixed(2) }}</strong></span></n-gi>
      <n-gi><n-text depth="3" style="font-size:12px;">{{ $t('terminal.spread') }}</n-text> <strong :class="{ 'flash-num': spreadFlash }" style="font-size:13px;display:inline-block;padding:1px 4px;border-radius:3px;transition:background .15s;">{{ store.spread.toFixed(2) }}</strong></n-gi>
      <n-gi><n-text depth="3" style="font-size:12px;">{{ $t('terminal.mid') }}</n-text> <span class="price-gold" style="font-size:13px;"><strong>{{ store.midPrice.toFixed(2) }}</strong></span></n-gi>
    </n-grid>

    <!-- 指标选择 — 紧凑网格布局 -->
    <n-grid :cols="4" :x-gap="8" :y-gap="4" style="margin-bottom: 6px;">
      <n-gi>
        <n-space size="small" align="center">
          <n-checkbox v-model:checked="showEMA" size="small" @update:checked="applyOverlay">EMA</n-checkbox>
          <n-input v-if="showEMA" v-model:value="emaPeriods" size="tiny" placeholder="20,50,200" style="width: 88px;" @change="applyOverlay" />
        </n-space>
      </n-gi>
      <n-gi>
        <n-space size="small" align="center">
          <n-checkbox v-model:checked="showSMA" size="small" @update:checked="applyOverlay">SMA</n-checkbox>
          <n-input v-if="showSMA" v-model:value="smaPeriods" size="tiny" placeholder="20,50" style="width: 88px;" @change="applyOverlay" />
        </n-space>
      </n-gi>
      <n-gi>
        <n-space size="small" align="center">
          <n-checkbox v-model:checked="showBB" size="small" @update:checked="applyOverlay">BB</n-checkbox>
          <template v-if="showBB">
            <app-input-number v-model:value="bbPeriod" size="tiny" :min="2" :max="200" style="width: 80px;" @update:value="applyOverlay" />
            <n-text depth="3" style="font-size:10px;">×</n-text>
            <app-input-number v-model:value="bbStd" size="tiny" :min="1" :max="5" :step="0.1" style="width: 72px;" @update:value="applyOverlay" />
          </template>
        </n-space>
      </n-gi>
      <n-gi>
        <n-space size="small" align="center">
          <n-checkbox v-model:checked="showRSI" size="small">RSI</n-checkbox>
          <template v-if="showRSI">
            <app-input-number v-model:value="rsiPeriod" size="tiny" :min="2" :max="100" style="width: 72px;" @update:value="refreshRSI" />
            <app-input-number v-model:value="rsiOb" size="tiny" :min="50" :max="100" style="width: 68px;" @update:value="refreshRSI" />
            <app-input-number v-model:value="rsiOs" size="tiny" :min="0" :max="50" style="width: 68px;" @update:value="refreshRSI" />
          </template>
        </n-space>
      </n-gi>
      <n-gi>
        <n-space size="small" align="center">
          <n-checkbox v-model:checked="showStoch" size="small">Stoch</n-checkbox>
          <template v-if="showStoch">
            <app-input-number v-model:value="stochK" size="tiny" :min="2" :max="100" style="width: 68px;" @update:value="refreshStoch" />
            <app-input-number v-model:value="stochKSmooth" size="tiny" :min="1" :max="20" style="width: 60px;" @update:value="refreshStoch" />
            <app-input-number v-model:value="stochDSmooth" size="tiny" :min="1" :max="20" style="width: 60px;" @update:value="refreshStoch" />
          </template>
        </n-space>
      </n-gi>
      <n-gi>
        <n-space size="small" align="center">
          <n-checkbox v-model:checked="showMACD" size="small">MACD</n-checkbox>
          <template v-if="showMACD">
            <app-input-number v-model:value="macdFast" size="tiny" :min="2" :max="200" style="width: 68px;" @update:value="refreshMACD" />
            <app-input-number v-model:value="macdSlow" size="tiny" :min="2" :max="200" style="width: 68px;" @update:value="refreshMACD" />
            <app-input-number v-model:value="macdSignal" size="tiny" :min="1" :max="50" style="width: 68px;" @update:value="refreshMACD" />
          </template>
        </n-space>
      </n-gi>
      <n-gi>
        <n-space size="small" align="center">
          <n-checkbox v-model:checked="showATR" size="small">ATR</n-checkbox>
          <app-input-number v-if="showATR" v-model:value="atrPeriod" size="tiny" :min="2" :max="100" style="width: 72px;" @update:value="refreshATR" />
        </n-space>
      </n-gi>
      <n-gi>
        <n-space size="small" align="center">
          <n-checkbox v-model:checked="showVolume" size="small">{{ $t('terminal.volume') }}</n-checkbox>
        </n-space>
      </n-gi>
    </n-grid>

    <!-- 主图 + 加载/空态覆盖 -->
    <div ref="chartContainer" style="width: 100%; height: 420px; position: relative;">
      <div v-if="store.loading" style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: #1a1d23; z-index: 1;">
        <n-spin size="large" />
      </div>
      <div v-else-if="!store.loading && store.candles.length === 0" style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: #1a1d23; z-index: 1;">
        <n-result status="info" :title="$t('terminal.no_data')" :description="$t('terminal.no_data_desc')" size="small" />
      </div>
    </div>

    <!-- 副图区域（按需渲染） -->
    <div v-if="showRSI" ref="rsiRef" style="width: 100%; height: 110px; position: relative;">
      <n-text depth="3" style="position: absolute; top: 2px; left: 8px; font-size: 10px; z-index: 2;">{{ $t('terminal.rsi_label', {period: rsiPeriod, ob: rsiOb, os: rsiOs}) }}</n-text>
    </div>
    <div v-if="showStoch" ref="stochRef" style="width: 100%; height: 110px; position: relative;">
      <n-text depth="3" style="position: absolute; top: 2px; left: 8px; font-size: 10px; z-index: 2;">Stoch ({{ stochK }},{{ stochKSmooth }},{{ stochDSmooth }})</n-text>
    </div>
    <div v-if="showMACD" ref="macdRef" style="width: 100%; height: 110px; position: relative;">
      <n-text depth="3" style="position: absolute; top: 2px; left: 8px; font-size: 10px; z-index: 2;">MACD ({{ macdFast }},{{ macdSlow }},{{ macdSignal }})</n-text>
    </div>
    <div v-if="showATR" ref="atrRef" style="width: 100%; height: 110px; position: relative;">
      <n-text depth="3" style="position: absolute; top: 2px; left: 8px; font-size: 10px; z-index: 2;">ATR ({{ atrPeriod }})</n-text>
    </div>
    <div v-if="showVolume" ref="volRef" style="width: 100%; height: 110px; position: relative;">
      <n-text depth="3" style="position: absolute; top: 2px; left: 8px; font-size: 10px; z-index: 2;">Volume</n-text>
    </div>
  </n-card>
</template>
