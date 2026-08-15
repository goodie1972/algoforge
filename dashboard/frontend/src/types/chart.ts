/**
 * chart.ts — 图表核心类型定义
 *
 * 统一 TradingTerminal / MainChart / IndicatorPanes / chartSync 的类型
 */

import type { UTCTimestamp } from 'lightweight-charts'

// ── 基础数据类型 ──────────────────────────────────────

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

// ── 副图配置 ──────────────────────────────────────────

export type PaneName =
  | 'rsi' | 'stoch' | 'macd' | 'atr' | 'volume'
  | 'adx' | 'di' | 'mfi' | 'bbi'

export interface PaneConfig {
  name: PaneName
  label: string
  height: number
  showRefLines?: boolean
  refLines?: { value: number; color: string; style: number }[]
}

// ── 指标参数 ──────────────────────────────────────────

export interface IndicatorParams {
  // EMA
  ema1: number
  ema2: number
  ema3: number
  // SMA
  sma1: number
  sma2: number
  // BB
  bbPeriod: number
  bbStd: number
  // RSI
  rsiPeriod: number
  rsiOb: number
  rsiOs: number
  // Stoch
  stochK: number
  stochKSmooth: number
  stochDSmooth: number
  // MACD
  macdFast: number
  macdSlow: number
  macdSignal: number
  // ATR
  atrPeriod: number
  // ADX
  adxPeriod: number
  // DI
  diPeriod: number
  // MFI
  mfiPeriod: number
}

// ── 图表联动 ──────────────────────────────────────────

export interface SyncLock {
  value: boolean
}

export interface ChartRef {
  chart: any
  candleSeries: any
  paneCharts: Record<string, any>
  paneSeries: Record<string, any>
  chartContainer: HTMLDivElement | undefined
  lock: SyncLock
}

// ── 时间轴类型转换 ────────────────────────────────────

export function castTime<T extends { time: number }>(
  arr: T[]
): (T & { time: UTCTimestamp })[] {
  return arr.map(p => ({ ...p, time: p.time as UTCTimestamp }))
}
