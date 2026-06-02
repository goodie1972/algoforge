// TypeScript 类型定义
export interface AccountInfo {
  login: number
  balance: number
  equity: number
  margin: number
  free_margin: number
  currency: string
  leverage: number
}

export interface Position {
  ticket: number
  symbol: string
  order_type: string
  volume: number
  open_price: number
  current_price: number
  stop_loss: number
  take_profit: number
  profit: number
  swap: number
  commission: number
  magic: number
  comment: string
  open_time: string
}

export interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface TickPrice {
  bid: number
  ask: number
  spread: number
  symbol?: string
}

export interface LogEntry {
  time: string
  level: string
  name: string
  message: string
}

export interface EngineStatus {
  status: 'running' | 'stopped' | 'uninitialized'
  uptime_seconds: number
  started_at?: string
  bridge_connected?: boolean
}

export interface WsMessage {
  channel: 'prices' | 'positions' | 'account' | 'signals' | 'logs' | 'status'
  data: any
}

export type EngineStatusType = 'running' | 'stopped' | 'uninitialized' | 'error'

// 回测类型
export interface BacktestRequest {
  strategies: string[]
  symbol?: string
  timeframe?: string
  start_date: string
  end_date: string
  initial_cash?: number
  commission?: number
}

export interface BacktestJob {
  job_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  progress?: string
  error?: string
  created_at?: string
  completed_at?: string
}

export interface BacktestTrade {
  entry_time: number
  exit_time: number
  direction: string
  entry_price: number
  exit_price: number
  pnl: number
  strategy: string
}

export interface BacktestResult {
  total_return: number
  total_return_pct: number
  total_trades: number
  win_rate: number
  max_drawdown: number
  sharpe_ratio: number
  equity_curve: Array<{ time: number; value: number }>
  trades: BacktestTrade[]
  by_strategy: Record<string, {
    total_pnl: number
    total_return_pct: number
    total_trades: number
    max_drawdown: number
    trades: BacktestTrade[]
    equity_curve: Array<{ time: number; value: number }>
  }>
}

export interface ClosedTrade {
  ticket: number
  symbol: string
  order_type: string
  volume: number
  entry_price: number
  exit_price: number
  pnl: number
  stop_loss: number
  take_profit: number
  swap: number
  commission: number
  magic: number
  strategy: string
  open_time: string
  close_time: string
  hold_seconds: number
  exit_reason: string
}

export interface BacktestHistoryItem {
  job_id: string
  status: string
  created_at: string
  params: BacktestRequest
  result_summary: Partial<BacktestResult> | null
}
