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
  time: string
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
