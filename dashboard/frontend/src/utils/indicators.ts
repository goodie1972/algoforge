// 技术指标计算 — 纯前端从 K 线数据计算
export interface CandleData {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

export interface LinePoint {
  time: number
  value: number
}

export interface BandPoint {
  time: number
  upper: number
  middle: number
  lower: number
}

export interface HistogramPoint {
  time: number
  value: number
  color?: string
}

// ---- 简单移动平均 ----
export function calcSMA(candles: CandleData[], period: number): LinePoint[] {
  const result: LinePoint[] = []
  for (let i = period - 1; i < candles.length; i++) {
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) sum += candles[j].close
    result.push({ time: candles[i].time, value: sum / period })
  }
  return result
}

// ---- 指数移动平均 ----
export function calcEMA(candles: CandleData[], period: number): LinePoint[] {
  const result: LinePoint[] = []
  const k = 2 / (period + 1)
  if (candles.length < period) return result
  // 初始值用 SMA
  let sum = 0
  for (let i = 0; i < period; i++) sum += candles[i].close
  let ema = sum / period
  result.push({ time: candles[period - 1].time, value: ema })
  for (let i = period; i < candles.length; i++) {
    ema = candles[i].close * k + ema * (1 - k)
    result.push({ time: candles[i].time, value: ema })
  }
  return result
}

// ---- 布林带 ----
export function calcBollinger(candles: CandleData[], period: number, multiplier: number = 2): BandPoint[] {
  const sma = calcSMA(candles, period)
  const result: BandPoint[] = []
  // 用 SMA 时间索引对齐原始 candles
  let smaI = 0
  for (let i = period - 1; i < candles.length; i++, smaI++) {
    let variance = 0
    for (let j = i - period + 1; j <= i; j++) {
      variance += (candles[j].close - sma[smaI].value) ** 2
    }
    const std = Math.sqrt(variance / period)
    result.push({
      time: candles[i].time,
      upper: sma[smaI].value + multiplier * std,
      middle: sma[smaI].value,
      lower: sma[smaI].value - multiplier * std,
    })
  }
  return result
}

// ---- RSI ----
export function calcRSI(candles: CandleData[], period: number = 14): LinePoint[] {
  const result: LinePoint[] = []
  if (candles.length < period + 1) return result
  let gains = 0, losses = 0
  for (let i = 1; i <= period; i++) {
    const diff = candles[i].close - candles[i - 1].close
    if (diff >= 0) gains += diff
    else losses -= diff
  }
  let avgGain = gains / period
  let avgLoss = losses / period
  result.push({ time: candles[period].time, value: avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss) })
  for (let i = period + 1; i < candles.length; i++) {
    const diff = candles[i].close - candles[i - 1].close
    const gain = diff >= 0 ? diff : 0
    const loss = diff < 0 ? -diff : 0
    avgGain = (avgGain * (period - 1) + gain) / period
    avgLoss = (avgLoss * (period - 1) + loss) / period
    const rsi = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
    result.push({ time: candles[i].time, value: rsi })
  }
  return result
}

// ---- Stochastic ----
export function calcStoch(
  candles: CandleData[],
  kPeriod: number = 14,
  kSmooth: number = 3,
  dSmooth: number = 3,
): { k: LinePoint[]; d: LinePoint[] } {
  const rawK: LinePoint[] = []
  for (let i = kPeriod - 1; i < candles.length; i++) {
    let highest = candles[i].high
    let lowest = candles[i].low
    for (let j = i - kPeriod + 1; j <= i; j++) {
      if (candles[j].high > highest) highest = candles[j].high
      if (candles[j].low < lowest) lowest = candles[j].low
    }
    const range = highest - lowest
    const val = range === 0 ? 100 : ((candles[i].close - lowest) / range) * 100
    rawK.push({ time: candles[i].time, value: val })
  }
  // 平滑 %K → smoothK, 再平滑 → %D
  const smoothK = smoothLine(rawK, kSmooth)
  const dLine = smoothLine(smoothK, dSmooth)
  return { k: smoothK, d: dLine }
}

function smoothLine(data: LinePoint[], period: number): LinePoint[] {
  const result: LinePoint[] = []
  for (let i = period - 1; i < data.length; i++) {
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) sum += data[j].value
    result.push({ time: data[i].time, value: sum / period })
  }
  return result
}

// ---- MACD ----
export function calcMACD(
  candles: CandleData[],
  fast: number = 12,
  slow: number = 26,
  signal: number = 9,
): { macd: LinePoint[]; signal: LinePoint[]; histogram: HistogramPoint[] } {
  const emaFast = calcEMA(candles, fast)
  const emaSlow = calcEMA(candles, slow)
  // 对齐时间（用 slow 的时间轴，因为 slow 更长）
  const macdLine: LinePoint[] = []
  for (let i = 0; i < emaSlow.length; i++) {
    // 找到相同时间的 fast EMA
    const fastVal = emaFast.find(p => p.time === emaSlow[i].time)
    if (fastVal) {
      macdLine.push({ time: emaSlow[i].time, value: fastVal.value - emaSlow[i].value })
    }
  }
  // Signal line = EMA of MACD line
  const signalLine = calcEMAFromLine(macdLine, signal)
  // Histogram = MACD - Signal
  const histogram: HistogramPoint[] = []
  for (const sig of signalLine) {
    const macdPt = macdLine.find(p => p.time === sig.time)
    if (macdPt) {
      const hVal = macdPt.value - sig.value
      histogram.push({
        time: sig.time,
        value: hVal,
        color: hVal >= 0 ? '#0ecb81' : '#f6465d',
      })
    }
  }
  return { macd: macdLine, signal: signalLine, histogram }
}

function calcEMAFromLine(data: LinePoint[], period: number): LinePoint[] {
  if (data.length < period) return []
  const k = 2 / (period + 1)
  let sum = 0
  for (let i = 0; i < period; i++) sum += data[i].value
  let ema = sum / period
  const result: LinePoint[] = [{ time: data[period - 1].time, value: ema }]
  for (let i = period; i < data.length; i++) {
    ema = data[i].value * k + ema * (1 - k)
    result.push({ time: data[i].time, value: ema })
  }
  return result
}

// ---- ATR ----
export function calcATR(candles: CandleData[], period: number = 14): LinePoint[] {
  const tr: LinePoint[] = []
  for (let i = 0; i < candles.length; i++) {
    if (i === 0) {
      tr.push({ time: candles[i].time, value: candles[i].high - candles[i].low })
    } else {
      const highLow = candles[i].high - candles[i].low
      const highPrev = Math.abs(candles[i].high - candles[i - 1].close)
      const lowPrev = Math.abs(candles[i].low - candles[i - 1].close)
      tr.push({ time: candles[i].time, value: Math.max(highLow, highPrev, lowPrev) })
    }
  }
  // ATR = EMA of TR
  return calcEMAFromLine(tr, period)
}

// ---- Volume ----
export function calcVolume(candles: CandleData[]): HistogramPoint[] {
  return candles.map(c => ({
    time: c.time,
    value: c.volume || 0,
    color: c.close >= c.open ? '#0ecb81' : '#f6465d',
  }))
}
