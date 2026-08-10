// REST API 客户端
import axios from 'axios'
import type { AccountInfo, Position, Candle, TickPrice, LogEntry, EngineStatus, BacktestRequest, BacktestJob, BacktestResult, BacktestHistoryItem, ClosedTrade, TradeStats } from '@/types'

const http = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

// === 引擎 ===
export async function getEngineStatus(): Promise<EngineStatus> {
  const { data } = await http.get('/engine/status')
  return data
}

export async function startEngine(): Promise<void> {
  await http.post('/engine/start')
}

export async function stopEngine(): Promise<void> {
  await http.post('/engine/stop')
}

// === 账户 ===
export async function getAccount(): Promise<AccountInfo> {
  const { data } = await http.get('/account')
  return data
}

// === 持仓 ===
export async function getPositions(): Promise<Position[]> {
  const { data } = await http.get('/positions')
  return data
}

export async function closePosition(ticket: number, volume?: number): Promise<void> {
  await http.post(`/positions/${ticket}/close`, { volume })
}

export async function modifyPosition(ticket: number, sl?: number, tp?: number): Promise<void> {
  await http.post(`/positions/${ticket}/modify`, { sl, tp })
}

// === 配置 ===
export async function getConfig(): Promise<Record<string, any>> {
  const { data } = await http.get('/config')
  return data
}

export async function updateConfig(updates: Record<string, any>): Promise<void> {
  await http.post('/config', { updates })
}

export async function resetConfig(key?: string): Promise<void> {
  await http.post('/config/reset', { key })
}

// === 策略池 ===
export async function getStrategyPool(): Promise<Record<string, any>> {
  const { data } = await http.get('/config/strategy-pool')
  return data
}

export async function updateStrategyPool(pool: Record<string, any>): Promise<void> {
  await http.post('/config/strategy-pool', { pool })
}

// === 协调器 ===
export async function getCoordinator(): Promise<Record<string, any>> {
  const { data } = await http.get('/config/coordinator')
  return data
}

export async function updateCoordinator(cfg: Record<string, any>): Promise<void> {
  await http.post('/config/coordinator', { config: cfg })
}

// === 纸面交易配置 ===
export async function getPaperConfig(): Promise<any> {
  const { data } = await http.get('/config/paper')
  return data
}

export async function updatePaperConfig(cfg: Record<string, any>): Promise<void> {
  await http.post('/config/paper', { config: cfg })
}

export async function resetPaperData(): Promise<void> {
  await http.post('/paper-trading/reset')
}

// === 行情 ===
export async function getPrice(): Promise<TickPrice> {
  const { data } = await http.get('/market/price')
  return data
}

export async function getCandles(timeframe = 'H1', count = 100): Promise<Candle[]> {
  const { data } = await http.get('/market/candles', { params: { timeframe, count } })
  return data
}

// === 新闻过滤 ===
export async function getNewsCalendar(): Promise<{
  is_blackout: boolean
  blackout_reason: string
  upcoming_events: Array<{
    title: string
    country: string
    impact: string
    datetime: string
    forecast: string
    previous: string
  }>
  blackout_windows: Array<{ start: string; end: string; title: string }>
}> {
  const { data } = await http.get('/news/calendar')
  return data
}

// === 日志 ===
export async function getLogs(level?: string, limit = 100, since?: string): Promise<LogEntry[]> {
  const { data } = await http.get('/logs', { params: { level, limit, since } })
  return data.logs
}

// === 历史成交 ===
export async function getTradeHistory(limit = 100): Promise<ClosedTrade[]> {
  const { data } = await http.get('/trades/history', { params: { limit } })
  return data
}

// === 策略收益统计 ===
export async function getTradeStats(params?: {
  strategies?: string
  from_date?: string
  to_date?: string
}): Promise<TradeStats> {
  const { data } = await http.get('/trades/stats', { params })
  return data
}

export async function getTradeAnalysis(ticket: number): Promise<any> {
  const { data } = await http.get(`/trades/analysis/${ticket}`)
  return data
}

export async function getTradeReport(): Promise<any> {
  const { data } = await http.get('/trades/report')
  return data
}

export async function getSignals(params?: { strategy?: string; status?: string; limit?: number }): Promise<any[]> {
  const { data } = await http.get('/signals', { params })
  return data
}

// === 报告 ===
export async function getReports(params?: {
  type?: string
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}): Promise<any> {
  const { data } = await http.get('/reports', { params })
  return data
}

export async function getReportById(id: number): Promise<any> {
  const { data } = await http.get(`/reports/${id}`)
  return data
}

export async function getReportTimeline(date: string, type = 'daily'): Promise<any> {
  const { data } = await http.get(`/reports/timeline/${date}`, { params: { type } })
  return data
}

export async function generateReport(type = 'daily', date?: string): Promise<any> {
  const { data } = await http.post('/reports/generate', null, { params: { type, date } })
  return data
}

// === 新闻预判报告（已迁移至 gold_news 系统） ===

// === 回测 ===
export async function runBacktest(params: BacktestRequest): Promise<{ job_id: string; status: string }> {
  const { data } = await http.post('/backtest/run', params)
  return data
}

export async function getBacktestStatus(jobId: string): Promise<BacktestJob> {
  const { data } = await http.get(`/backtest/status/${jobId}`)
  return data
}

export async function getBacktestResults(jobId: string): Promise<BacktestJob & { result?: BacktestResult }> {
  const { data } = await http.get(`/backtest/results/${jobId}`)
  return data
}

export async function getBacktestHistory(limit = 20): Promise<BacktestHistoryItem[]> {
  const { data } = await http.get('/backtest/history', { params: { limit } })
  return data
}

export interface VersionInfo {
  version: string
  commit: string
  branch: string
  dirty: boolean
  display: string
  has_update: boolean
  behind_count: number
}

export async function getVersionInfo(): Promise<VersionInfo> {
  const { data } = await http.get('/version')
  return data
}

export interface ChangelogCommit {
  hash: string
  date: string
  subject: string
}

export async function getChangelog(limit = 20): Promise<{ commits: ChangelogCommit[]; error?: string }> {
  const { data } = await http.get('/version/changelog', { params: { limit } })
  return data
}

export async function getRemoteChangelog(limit = 20): Promise<{ commits: ChangelogCommit[] }> {
  const { data } = await http.get('/version/remote-changelog', { params: { limit } })
  return data
}

export async function updateVersion(): Promise<{ success: boolean; message: string; version?: VersionInfo }> {
  const { data } = await http.post('/version/update')
  return data
}

export interface BiasState {
  direction: 'bullish' | 'bearish' | 'neutral' | null
  score: number
  updated_at: number
  source: string
  age_seconds: number | null
}

export async function getBiasState(): Promise<BiasState> {
  const { data } = await http.get('/version/bias-state')
  return data
}

export async function forceRefreshBias(): Promise<{ direction: string | null; full: BiasState }> {
  const { data } = await http.post('/version/bias-state/refresh')
  return data
}
