// REST API 客户端
import axios from 'axios'
import type { AccountInfo, Position, Candle, TickPrice, LogEntry, EngineStatus, BacktestRequest, BacktestJob, BacktestResult, BacktestHistoryItem, ClosedTrade } from '@/types'

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
export async function getLogs(level?: string, limit = 100): Promise<LogEntry[]> {
  const { data } = await http.get('/logs', { params: { level, limit } })
  return data.logs
}

// === 历史成交 ===
export async function getTradeHistory(limit = 100): Promise<ClosedTrade[]> {
  const { data } = await http.get('/trades/history', { params: { limit } })
  return data
}

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
