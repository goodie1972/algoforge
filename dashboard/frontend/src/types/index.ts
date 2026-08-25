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
  timestamp: string
  level: string
  name: string
  message: string
  _id?: number
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

// 监控告警
export interface PatrolAlert {
  id: number
  time: string
  level: 'info' | 'warning' | 'critical'
  message: string
  key?: string  // 去重/已读标识，clearAlerts 后同 key 不再出现
}

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

// 策略收益统计（MT4 标准报表）
export interface StrategyStats {
  total_net_profit: number
  gross_profit: number
  gross_loss: number
  profit_factor: number | string
  expected_payoff: number
  total_trades: number
  short_trades: number
  short_won: number
  short_won_pct: number
  long_trades: number
  long_won: number
  long_won_pct: number
  profit_trades: number
  loss_trades: number
  win_rate: number
  largest_profit_trade: number
  largest_loss_trade: number
  avg_profit_trade: number
  avg_loss_trade: number
  ratio_avg_profit_loss: number
  avg_hold_seconds: number
  max_consecutive_wins: number
  max_consecutive_losses: number
  max_consecutive_wins_pnl: number
  max_consecutive_losses_pnl: number
  total_commission: number
  total_swap: number
}

export interface StrategyVersionStats extends StrategyStats {
  magic: number
  strategy: string
  version: string
}

export interface StrategyFamilyStats extends StrategyStats {
  magic: string  // 4-digit PPNN
  strategy: string
  versions: StrategyVersionStats[]
}

export interface TradeStats {
  summary: StrategyStats
  by_magic: Record<string, StrategyStats & { magic: number; strategy: string }>
  by_strategy: Record<string, StrategyFamilyStats>
}

// 单笔成交分析（GET /api/trades/analysis/{ticket}）
export interface TradeStrategyMeta {
  internal_name: string
  display: string
  timeframe: string
  version: string
  resolved_by: string
  desc: string
}

export interface TradeAiAnalysis {
  entry_logic: string
  exit_reason: string
  pnl_note: string
  model: string
}

export interface TradeAnalysis {
  entry_analysis?: {
    system?: string
    likely_conditions?: string[]
    factors?: { name: string; desc: string }[]
  }
  exit_analysis?: {
    label?: string
    logic?: string
    is_loss?: boolean
    loss_analysis?: { possible_reasons?: string[]; suggestions?: string[] }
  }
  // ── LLM 分析新增字段（可选，后端渐进上线）──
  strategy_meta?: TradeStrategyMeta | null
  ai_analysis?: TradeAiAnalysis | null
  analysis_source?: 'llm' | 'fallback'
  [key: string]: any
}

// LLM 服务状态
export interface LlmStatus {
  available: boolean
  model: string | null
}

// 新闻预判报告
// 新闻预判报告（已迁移至 gold_news 系统，此接口不再使用）
