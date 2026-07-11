<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()
const saving = ref(false)

interface StrategyMeta {
  id: string
  name: string
  display: string
  file: string
  backup_file: string | null
  default_magic: number
  default_timeframe: string
}

interface PoolEntry {
  enabled: boolean
  magic: number
  timeframe: string
  max_positions: number
  double_first: boolean
}

const allStrategies = ref<StrategyMeta[]>([])
const pool = ref<Record<string, PoolEntry>>({})
const expanded = ref<Set<string>>(new Set())
const loading = ref(true)

const timeframes = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1']

interface EntryFactor {
  name: string
  score: string
  detail: string
}

interface ExitRow {
  method: string
  normal: string
  widen?: string
}

// 策略进出场逻辑 (与交易终端一致)
interface StratLogic {
  desc: string
  exitWiden?: boolean
  exitNote?: string
  long: { entry: EntryFactor[]; exit: ExitRow[] }
  short: { entry: EntryFactor[]; exit: ExitRow[] }
}

const strategyLogics: Record<string, StratLogic> = {
  m30_rsi_v7: {
    desc: 'M30 RSI+布林带 v11 (5因子评分≥3, DI强度因子⑤, ADX>28趋势门禁EMA9/21, DI止盈判定)',
    exitWiden: true,
    exitNote: '趋势感知：同向(顺势)用加宽列，逆向(逆势)用正常列。DI止盈判定：移动止盈触发时+DI- -DI>10(BUY)/-DI-+DI>10(SELL)则趋势强，忽略止盈',
    long: {
      entry: [
        { name: 'MA14趋势', score: '+1', detail: 'MA14上升' },
        { name: 'BB触轨', score: '+1', detail: '触碰BB下轨' },
        { name: 'RSI超卖', score: '+1', detail: 'RSI < 30' },
        { name: 'RSI方向', score: '+1', detail: 'RSI连续3根上升' },
        { name: 'DI强度', score: '±1', detail: '|+DI- -DI|>10 给强度分(新⑤)' },
        { name: '总分门槛', score: '', detail: '阈值≥3入场' },
        { name: 'ADX门禁', score: '', detail: 'ADX>28时EMA9<EMA21禁多' },
        { name: '位置门禁', score: '', detail: '60根K线区间顶部10%禁多' },
      ],
      exit: [
        { method: '利润回撤止盈', normal: '峰值回撤25%(可配置)', widen: '同左' },
        { method: 'DI止盈判定', normal: 'DI差值>10忽略止盈', widen: '同左' },
        { method: 'ATR移动止盈(trail)', normal: '1.0×ATR', widen: '1.5×ATR' },
        { method: 'ATR硬止损(hard)', normal: '2.0×ATR', widen: '3.0×ATR' },
      ],
    },
    short: {
      entry: [
        { name: 'MA14趋势', score: '+1', detail: 'MA14下降' },
        { name: 'BB触轨', score: '+1', detail: '触碰BB上轨' },
        { name: 'RSI超买', score: '+1', detail: 'RSI > 65' },
        { name: 'RSI方向', score: '+1', detail: 'RSI连续3根下降' },
        { name: 'DI强度', score: '±1', detail: '|+DI- -DI|>10 给强度分(新⑤)' },
        { name: '总分门槛', score: '', detail: '阈值≥3入场' },
        { name: 'ADX门禁', score: '', detail: 'ADX>28时EMA9>EMA21禁空' },
        { name: '位置门禁', score: '', detail: '60根K线区间底部10%禁空' },
      ],
      exit: [
        { method: '利润回撤止盈', normal: '峰值回撤25%(可配置)', widen: '同左' },
        { method: 'DI止盈判定', normal: 'DI差值>10忽略止盈', widen: '同左' },
        { method: 'ATR移动止盈(trail)', normal: '1.0×ATR', widen: '1.5×ATR' },
        { method: 'ATR硬止损(hard)', normal: '2.0×ATR', widen: '3.0×ATR' },
      ],
    },
  },
  m30_stoch_T6V1: {
    desc: 'M30 Stoch 均值回归 (ADX<30+BB宽≤1.0纯震荡, v11 A5)',
    long: {
      entry: [
        { name: '震荡条件', score: '+1', detail: 'ADX<30 且 BB宽度≤1.0' },
        { name: 'K值位置', score: '+1', detail: 'K < 20 (超卖区)' },
        { name: '金叉确认', score: '+1', detail: 'K线上穿D线' },
        { name: '价格位置', score: '+1', detail: 'close < EMA21' },
        { name: '总分门槛', score: '', detail: '4条件全满足+无冲突入场' },
      ],
      exit: [
        { method: 'Stoch反向交叉', normal: 'close≥EMA21出场' },
        { method: 'misalign检测', normal: 'BB中轨方向≠K方向时提前出' },
        { method: 'ATR硬止损', normal: '1.0×ATR' },
      ],
    },
    short: {
      entry: [
        { name: '震荡条件', score: '+1', detail: 'ADX<30 且 BB宽度≤1.0' },
        { name: 'K值位置', score: '+1', detail: 'K > 80 (超买区)' },
        { name: '死叉确认', score: '+1', detail: 'K线下穿D线' },
        { name: '价格位置', score: '+1', detail: 'close > EMA21' },
        { name: '总分门槛', score: '', detail: '4条件全满足+无冲突入场' },
      ],
      exit: [
        { method: 'Stoch反向交叉', normal: 'close≤EMA21出场' },
        { method: 'misalign检测', normal: '提前出场' },
        { method: 'ATR硬止损', normal: '1.0×ATR' },
      ],
    },
  },
  m30_stoch_T6V8: {
    desc: 'M30 Stoch v3 震荡+趋势双模 (ADX<28窄幅/宽幅震荡, ≥28趋势顺势; 利润回撤止盈)',
    long: {
      entry: [
        { name: '窄幅震荡', score: '', detail: 'ADX<28+BB≤2%: K<20+金叉+close<EMA21' },
        { name: '宽幅震荡', score: '', detail: 'ADX<28+BB>2%: low≤BB下轨+K<15+DI金叉' },
        { name: '趋势模式', score: '', detail: 'ADX≥28: +DI->DI-+10+close>EMA21+金叉' },
        { name: 'ADX判定', score: '', detail: 'ADX<28→震荡, ≥28→趋势顺势' },
      ],
      exit: [
        { method: '利润回撤止盈', normal: '峰值回撤25%止盈(可配置)' },
        { method: '震荡出场', normal: 'Stoch反向交叉出场 / misalign提前出' },
        { method: '趋势出场', normal: '峰谷回撤2.0ATR止盈 / 固定TP 4.0ATR' },
        { method: '趋势衰减', normal: 'ADX<20衰减出场 / DI方向反转出' },
        { method: '硬止损', normal: '震荡1.0×ATR / 趋势2.0×ATR' },
      ],
    },
    short: {
      entry: [
        { name: '窄幅震荡', score: '', detail: 'ADX<28+BB≤2%: K>80+死叉+close>EMA21' },
        { name: '宽幅震荡', score: '', detail: 'ADX<28+BB>2%: high≥BB上轨+K>85+DI死叉' },
        { name: '趋势模式', score: '', detail: 'ADX≥28: -DI->+DI+10+close<EMA21+死叉' },
        { name: 'ADX判定', score: '', detail: 'ADX<28→震荡, ≥28→趋势顺势' },
      ],
      exit: [
        { method: '利润回撤止盈', normal: '峰值回撤25%止盈(可配置)' },
        { method: '震荡出场', normal: 'Stoch反向交叉出场 / misalign提前出' },
        { method: '趋势出场', normal: '峰谷回撤2.0ATR止盈 / 固定TP 4.0ATR' },
        { method: '趋势衰减', normal: 'ADX<20衰减出场 / DI方向反转出' },
        { method: '硬止损', normal: '震荡1.0×ATR / 趋势2.0×ATR' },
      ],
    },
  },
  rsi_grading_m30: {
    desc: 'M30 RSI分级评分 v5 (5因子评分≥2, ADX>28趋势门禁EMA9/21, 趋势感知出场顺2.0逆1.0, 利润回撤止盈)',
    exitWiden: true,
    exitNote: '出场趋势感知：顺趋势(同向)用加宽列，逆趋势(反向)用正常列',
    long: {
      entry: [
        { name: 'RSI深度超卖', score: '+2', detail: 'RSI < 20' },
        { name: 'RSI轻度超卖', score: '+1', detail: 'RSI 20~30' },
        { name: 'MA14趋势', score: '+1', detail: 'MA14上升' },
        { name: 'BB触轨', score: '+1', detail: '触碰BB下轨' },
        { name: '趋势增强(⑤)', score: '+1~+2', detail: 'ADX>28时: EMA9/21定方向+DI差值定强度' },
        { name: '总分门槛', score: '', detail: '阈值≥2入场' },
        { name: 'ADX门禁', score: '', detail: 'ADX>28时禁反向(EMA9/21)' },
      ],
      exit: [
        { method: '利润回撤止盈', normal: '峰值回撤25%(可配置)', widen: '同左' },
        { method: 'ATR移动止盈(trail)', normal: '1.0×ATR(逆势)', widen: '2.0×ATR(顺势)' },
        { method: 'ATR硬止损(hard)', normal: '1.0×ATR(逆势)', widen: '2.0×ATR(顺势)' },
      ],
    },
    short: {
      entry: [
        { name: 'RSI深度超买', score: '+2', detail: 'RSI > 70' },
        { name: 'RSI轻度超买', score: '+1', detail: 'RSI 65~70' },
        { name: 'MA14趋势', score: '+1', detail: 'MA14下降' },
        { name: 'BB触轨', score: '+1', detail: '触碰BB上轨' },
        { name: '趋势增强(⑤)', score: '+1~+2', detail: 'ADX>28时: EMA9/21定方向+DI差值定强度' },
        { name: '总分门槛', score: '', detail: '阈值≥2入场' },
        { name: 'ADX门禁', score: '', detail: 'ADX>28时禁反向(EMA9/21)' },
      ],
      exit: [
        { method: '利润回撤止盈', normal: '峰值回撤25%(可配置)', widen: '同左' },
        { method: 'ATR移动止盈(trail)', normal: '1.0×ATR(逆势)', widen: '2.0×ATR(顺势)' },
        { method: 'ATR硬止损(hard)', normal: '1.0×ATR(逆势)', widen: '2.0×ATR(顺势)' },
      ],
    },
  },
  h1_v6_hybrid_v6: {
    desc: '[已下架] H1 8因子评分 V6 混合 (602笔亏$166, 4个超卖因子全亏)',
    exitWiden: true,
    exitNote: '趋势感知：同向(顺势)用加宽列，逆向(逆势)用正常列',
    long: {
      entry: [
        { name: 'SMA200趋势', score: '+1', detail: 'close > SMA200 (趋势评分+)' },
        { name: 'KDJ超卖', score: '+1', detail: 'Stoch K < 30' },
        { name: 'BB位置', score: '+1', detail: '触碰BB下轨' },
        { name: 'KC位置', score: '+1', detail: '触碰Keltner下轨' },
        { name: 'M30方向', score: '+1', detail: 'M30 K线上升 (小周期共振)' },
        { name: 'MACD底背离', score: '+1', detail: '价格新低+MACD柱升高' },
        { name: 'RSI偏低', score: '+1', detail: 'RSI < 30' },
        { name: '低波动', score: '+1', detail: 'ATR < 均值 (波动收缩)' },
        { name: '总分门槛', score: '', detail: '8因子≥3入场, 逆势≥5' },
        { name: '位置门禁', score: '', detail: '60根K线顶部10%禁多' },
        { name: '急跌惩罚', score: '', detail: '急跌>1.5%暂停做多' },
      ],
      exit: [
        { method: '利润回撤止盈', normal: '峰值回撤止盈(可配置)', widen: '同左' },
        { method: 'ATR移动止盈(trail)', normal: '1.0×ATR', widen: '1.5×ATR' },
        { method: 'ATR硬止损(hard)', normal: '2.0×ATR', widen: '3.0×ATR' },
      ],
    },
    short: {
      entry: [
        { name: 'SMA200趋势', score: '+1', detail: 'close < SMA200 (趋势评分-)' },
        { name: 'KDJ超买', score: '+1', detail: 'Stoch K > 65' },
        { name: 'BB位置', score: '+1', detail: '触碰BB上轨' },
        { name: 'KC位置', score: '+1', detail: '触碰Keltner上轨' },
        { name: 'M30方向', score: '+1', detail: 'M30 K线下降' },
        { name: 'MACD顶背离', score: '+1', detail: '价格新高+MACD柱降低' },
        { name: 'RSI偏高', score: '+1', detail: 'RSI > 65' },
        { name: 'M30趋势门禁', score: '', detail: 'M30上升+close>SMA200时空单阈值3→4' },
        { name: '总分门槛', score: '', detail: '8因子≥3入场, 逆势≥4' },
        { name: '位置门禁', score: '', detail: '60根K线底部10%禁空' },
        { name: '急涨惩罚', score: '', detail: '急涨>1.5%暂停做空' },
      ],
      exit: [
        { method: '利润回撤止盈', normal: '峰值回撤止盈(可配置)', widen: '同左' },
        { method: 'ATR移动止盈(trail)', normal: '1.0×ATR', widen: '1.5×ATR' },
        { method: 'ATR硬止损(hard)', normal: '2.0×ATR', widen: '3.0×ATR' },
      ],
    },
  },
  sanqing_h1_v6: {
    desc: 'H1 EMA9/21 + ATR14 6因子评分 v7 (ADX>25阈值4/ADX≤25阈值5, 纯顺趋势, 自适应回撤止盈, 位置门禁)',
    exitWiden: true,
    exitNote: '趋势感知：同向(顺势)用加宽列，逆向(逆势)用正常列。自适应回撤：峰值<1ATR→50%, 1~2ATR→40%, ≥2ATR→25%',
    long: {
      entry: [
        { name: 'EMA趋势', score: '+2', detail: 'EMA9 > EMA21 (上升趋势)' },
        { name: 'EMA金叉', score: '+1', detail: 'EMA9上穿EMA21' },
        { name: '触碰EMA9反弹', score: '+2', detail: 'low≤EMA9×1.002 且 close>EMA9' },
        { name: '实体幅度', score: '+1', detail: '实体/ATR > 1.0' },
        { name: '高成交量', score: '+1', detail: 'volume > 均量×1.3' },
        { name: '吞没形态', score: '+2', detail: 'body中值≥1.5 且 body/prev_max≥1.5' },
        { name: 'ADX规则', score: '', detail: 'ADX>25时阈值4, ADX≤25时阈值5' },
        { name: '位置门禁', score: '', detail: '60根K线顶部10%禁多' },
      ],
      exit: [
        { method: '自适应回撤止盈', normal: '峰值<1ATR:回撤50%', widen: '峰值≥2ATR:回撤25%' },
        { method: 'ATR移动止盈(trail)', normal: '1.0×ATR', widen: '2.5×ATR' },
        { method: 'ATR硬止损(hard)', normal: '2.0×ATR', widen: '4.0×ATR' },
      ],
    },
    short: {
      entry: [
        { name: 'EMA趋势', score: '+2', detail: 'EMA9 < EMA21 (下降趋势)' },
        { name: 'EMA死叉', score: '+1', detail: 'EMA9下穿EMA21' },
        { name: '触碰EMA9回落', score: '+2', detail: 'high≥EMA9×0.998 且 close<EMA9' },
        { name: '实体幅度', score: '+1', detail: '实体/ATR > 1.0' },
        { name: '高成交量', score: '+1', detail: 'volume > 均量×1.3' },
        { name: '吞没形态', score: '+2', detail: 'body中值≥1.5 且 body/prev_max≥1.5' },
        { name: 'ADX规则', score: '', detail: 'ADX>25时阈值4, ADX≤25时阈值5' },
        { name: '位置门禁', score: '', detail: '60根K线底部10%禁空' },
      ],
      exit: [
        { method: '自适应回撤止盈', normal: '峰值<1ATR:回撤50%', widen: '峰值≥2ATR:回撤25%' },
        { method: 'ATR移动止盈(trail)', normal: '1.0×ATR', widen: '2.5×ATR' },
        { method: 'ATR硬止损(hard)', normal: '2.0×ATR', widen: '4.0×ATR' },
      ],
    },
  },
  gold_autoresearch_h1_v5: {
    desc: 'H1 4因子共识投票 v6 (4因子全真入场, 趋势感知出场, 利润回撤止盈, 位置门禁+RSI安全过滤)',
    exitWiden: true,
    exitNote: '趋势感知出场：同向(顺势)用加宽列，逆向(逆势)用正常列',
    long: {
      entry: [
        { name: '趋势', score: '+1', detail: 'EMA10 > EMA20 (上升趋势)' },
        { name: '动量', score: '+1', detail: 'MACD>信号线 或 Stoch金叉' },
        { name: '波动', score: '+1', detail: 'ADX>20 或 ATR上升 (有活性)' },
        { name: '安全过滤', score: '', detail: '非(BB上轨+RSI≥70), 防止追高' },
        { name: '入场规则', score: '', detail: '4因子全真才入场 (共识投票)' },
        { name: '位置门禁', score: '', detail: '60根K线顶部10%禁多' },
      ],
      exit: [
        { method: '利润回撤止盈', normal: '峰值回撤25%(可配置)', widen: '同左' },
        { method: 'ATR移动止盈(trail)', normal: '1.0×ATR(逆势)', widen: '1.5×ATR(顺势)' },
        { method: 'ATR硬止损(hard)', normal: '2.0×ATR(逆势)', widen: '3.0×ATR(顺势)' },
      ],
    },
    short: {
      entry: [
        { name: '趋势', score: '+1', detail: 'EMA10 < EMA20 (下降趋势)' },
        { name: '动量', score: '+1', detail: 'MACD<信号线 或 Stoch死叉' },
        { name: '波动', score: '+1', detail: 'ADX>20 或 ATR上升 (有活性)' },
        { name: '安全过滤', score: '', detail: 'RSI > 35 (RSI≤35封空)' },
        { name: '入场规则', score: '', detail: '4因子全真才入场 (共识投票)' },
        { name: '位置门禁', score: '', detail: '60根K线底部10%禁空' },
      ],
      exit: [
        { method: '利润回撤止盈', normal: '峰值回撤25%(可配置)', widen: '同左' },
        { method: 'ATR移动止盈(trail)', normal: '1.0×ATR(逆势)', widen: '1.5×ATR(顺势)' },
        { method: 'ATR硬止损(hard)', normal: '2.0×ATR(逆势)', widen: '3.0×ATR(顺势)' },
      ],
    },
  },
  mtf_resonance_h1: {
    desc: 'H1+M15 TA-Lib 形态共振 v3 (双周期同向反转+质量过滤, trail>hard让盈利多飞)',
    long: {
      entry: [
        { name: 'H1反转形态', score: '', detail: 'TA-Lib检测到反转形态 (CDLHAMMER, CDLMORNINGSTAR等)' },
        { name: 'M15共振', score: '', detail: '同窗口M15出现同向反转信号(完整M15数据)' },
        { name: '质量过滤', score: '', detail: 'H1 RSI中位超卖 + H1趋势向下 (BULL_FILTERS)' },
        { name: '共振原则', score: '', detail: '双周期形态一致才开仓, 否则等待' },
      ],
      exit: [
        { method: 'ATR移动止盈(trail)', normal: '2.0×ATR(宽松止盈)' },
        { method: 'ATR硬止损(hard)', normal: '1.0×ATR(紧止损)' },
      ],
    },
    short: {
      entry: [
        { name: 'H1反转形态', score: '', detail: 'TA-Lib检测到反转形态 (CDLSHOOTINGSTAR, CDLEVENINGSTAR等)' },
        { name: 'M15共振', score: '', detail: '同窗口M15出现同向反转信号(完整M15数据)' },
        { name: '质量过滤', score: '', detail: 'H1 RSI中位超买 + H1趋势向上 (BEAR_FILTERS)' },
        { name: '共振原则', score: '', detail: '双周期形态一致才开仓, 否则等待' },
      ],
      exit: [
        { method: 'ATR移动止盈(trail)', normal: '2.0×ATR(宽松止盈)' },
        { method: 'ATR硬止损(hard)', normal: '1.0×ATR(紧止损)' },
      ],
    },
  },
}

// 策略颜色映射 (按 name)
const strategyColors: Record<string, string> = {
  M30_rsi_bb: '#f0a020',
  gold_auto_research: '#20c080',
  mfi_bb_m30: '#00bcd4',
  mfi_bb_m30_optimized: '#00838f',
  m30_bb_deepreturn: '#ff7043',
  m30_bb_deepreturn_optimized: '#d84315',
  entry_score_pro: '#7c4dff',
  momentum_pulse_pro: '#ffa726',
  stoch_trend_h1: '#26c6da',
  stoch_trend_h1_optimized: '#00695c',
  sanqing_h1: '#9220f0',
  sanqing_h1_original: '#4a148c',
  rsi_grading_m30: '#e040a0',
  rsi_grading_m30_optimized: '#880e4f',
  bakome_backup: '#66bb6a',
  bakome_backup_optimized: '#2e7d32',
  viprasol_sniper: '#ef5350',
  xaubot_backup: '#8d6e63',
  multi_confluence_quant: '#808080',
  stoch_m30: '#20c080',
  stoch_trend_m30: '#2080f0',
  mtf_resonance_h1: '#2080f0',
}

// 已启用策略
const enabledCount = computed(() =>
  Object.values(pool.value).filter(p => p.enabled).length
)

onMounted(async () => {
  let fetched: StrategyMeta[] = []
  try {
    const res = await fetch('/api/strategies/available')
    const data = await res.json()
    fetched = data.strategies || []
  } catch (e) {
    console.error('获取策略清单失败', e)
  }

  await store.fetch()
  const existing = store.items.strategy_pool || {}

  const merged: Record<string, PoolEntry> = {}
  for (const meta of fetched) {
    const curr = (existing as any)[meta.id]
    merged[meta.id] = {
      enabled: curr?.enabled !== undefined ? curr.enabled : false,
      magic: curr?.magic || meta.default_magic,
      timeframe: curr?.timeframe || meta.default_timeframe,
      max_positions: curr?.max_positions ?? 1,
      double_first: curr?.double_first ?? false,
    }
  }
  pool.value = merged
  allStrategies.value = fetched
  loading.value = false
})

function toggleStrategy(id: string) {
  if (pool.value[id]) {
    pool.value[id].enabled = !pool.value[id].enabled
  }
}

function toggleExpand(id: string) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
  expanded.value = new Set(expanded.value)
}

function getLogic(name: string): StratLogic | null {
  return strategyLogics[name] || null
}

function getColor(name: string): string {
  return strategyColors[name] || '#808080'
}

function updateMagic(id: string, val: string) {
  const n = parseInt(val, 10)
  if (!isNaN(n) && pool.value[id]) {
    pool.value[id].magic = Math.min(999999, Math.max(100000, n))
  }
}

async function save() {
  saving.value = true
  try {
    // 只传 enabled=true 的到 runtime_config
    const payload: Record<string, any> = {}
    for (const [id, cfg] of Object.entries(pool.value)) {
      payload[id] = {
        enabled: cfg.enabled,
        magic: cfg.magic,
        timeframe: cfg.timeframe,
        max_positions: cfg.enabled ? (cfg.max_positions || 1) : 0,
        double_first: cfg.double_first,
      }
    }
    await store.updateStrategyPool(payload)
    message.success('策略配置已保存，引擎将在下个 tick 生效')
  } catch (e: any) {
    message.error(e?.message || '保存失败')
  }
  saving.value = false
}
</script>

<template>
  <n-space vertical size="medium">
    <n-alert type="info" :bordered="false" closable>
      共 {{ allStrategies.length }} 个策略，已启用 {{ enabledCount }} 个。
      左侧开关控制是否进入实盘交易。展开 > 查看完整进出场逻辑。
    </n-alert>

    <n-spin :show="loading">
      <n-empty v-if="!loading && !allStrategies.length" description="未发现可交易策略" />

      <n-card v-for="meta in allStrategies" :key="meta.id" size="small" :bordered="true"
        :style="{
          opacity: pool[meta.id]?.enabled ? 1 : 0.55,
          borderLeft: `4px solid ${getColor(meta.name)}`,
        }">

        <!-- 顶栏: 开关 + 名称 + 标签 + Magic + TF -->
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <n-switch :value="pool[meta.id]?.enabled"
              @update:value="toggleStrategy(meta.id)" size="small" />
            <n-text strong style="font-size: 14px;">{{ meta.display }}</n-text>
            <n-tag size="tiny" :bordered="false"
              :color="{ color: getColor(meta.name) }" text-color="#fff">
              {{ meta.name }}
            </n-tag>
            <n-tag v-if="meta.backup_file" size="tiny" :bordered="false" type="info">
              {{ meta.backup_file }}
            </n-tag>
          </div>

          <div style="display: flex; align-items: center; gap: 12px;">
            <n-space size="small" align="center">
              <n-text depth="3" style="font-size: 11px;">Magic</n-text>
              <n-input :value="String(pool[meta.id]?.magic || '')" size="tiny"
                style="width: 76px;" @click.stop
                @update:value="updateMagic(meta.id, $event)" />
            </n-space>
            <n-select v-model:value="pool[meta.id].timeframe"
              :options="timeframes.map(t => ({ label: t, value: t }))"
              size="tiny" style="width: 65px;" @click.stop />
            <n-button text size="tiny" style="font-size: 16px; width: 24px;"
              @click.stop="toggleExpand(meta.id)">
              {{ expanded.has(meta.id) ? '▼' : '▶' }}
            </n-button>
          </div>
        </div>

        <!-- 持仓参数 (展开后显示) -->
        <div v-if="expanded.has(meta.id)" style="margin-top: 6px;">
          <div style="display: flex; gap: 16px; align-items: center; margin-bottom: 8px;">
            <n-space align="center" size="small">
              <n-text depth="3" style="font-size: 11px;">最大持仓</n-text>
              <n-input-number v-model:value="pool[meta.id].max_positions"
                size="tiny" :min="1" :max="5" style="width: 60px;" @click.stop />
            </n-space>
            <n-space align="center" size="small">
              <n-text depth="3" style="font-size: 11px;">双倍首单</n-text>
              <n-switch v-model:value="pool[meta.id].double_first" size="small" @click.stop />
            </n-space>
          </div>

          <!-- 进出场逻辑 (双栏: 左做多右做空, 上入场下出场) -->
          <template v-if="getLogic(meta.name)">
            <n-text depth="2" style="font-size: 12px; display: block; margin-bottom: 8px;">
              {{ getLogic(meta.name)!.desc }}
            </n-text>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
              <!-- 做多 (左) -->
              <div style="border-left: 3px solid #0ecb81; padding-left: 8px;">
                <div style="font-weight: 600; color: #0ecb81; font-size: 12px; margin-bottom: 3px;">▲ 做多</div>
                <n-table size="small" bordered single-line :style="{ fontSize: '11px' }">
                  <thead>
                    <tr>
                      <th style="width: 20px; text-align: center;">#</th>
                      <th>因子</th>
                      <th style="width: 34px; text-align: center;">得分</th>
                      <th>条件</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(f, i) in getLogic(meta.name)!.long.entry" :key="'le'+i">
                      <td style="text-align: center; color: #8b8f97;">{{ i+1 }}</td>
                      <td>{{ f.name }}</td>
                      <td style="text-align: center;">
                        <span v-if="f.score" style="display:inline-block; padding:0 3px; background:#f0a020; color:#fff; font-weight:700; font-size:10px; border-radius:2px;">{{ f.score }}</span>
                      </td>
                      <td>{{ f.detail }}</td>
                    </tr>
                  </tbody>
                </n-table>
                <n-table size="small" bordered single-line :style="{ fontSize: '10px' }" style="margin-top: 3px;">
                  <thead>
                    <tr>
                      <th style="width:16px;text-align:center;">#</th>
                      <th>出场方式</th>
                      <th>正常模式</th>
                      <th v-if="getLogic(meta.name)!.exitWiden" style="text-align:center;">加宽</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(ex, i) in getLogic(meta.name)!.long.exit" :key="'lx'+i">
                      <td style="text-align:center;color:#8b8f97;">{{ i+1 }}</td>
                      <td>{{ ex.method }}</td>
                      <td>{{ ex.normal }}</td>
                      <td v-if="getLogic(meta.name)!.exitWiden" style="text-align:center;">{{ ex.widen || '—' }}</td>
                    </tr>
                  </tbody>
                </n-table>
                <div v-if="getLogic(meta.name)!.exitNote" style="font-size:10px;color:#8b8f97;margin-top:2px;">
                  {{ getLogic(meta.name)!.exitNote }}
                </div>
              </div>

              <!-- 做空 (右) -->
              <div style="border-left: 3px solid #f6465d; padding-left: 8px;">
                <div style="font-weight: 600; color: #f6465d; font-size: 12px; margin-bottom: 3px;">▼ 做空</div>
                <n-table size="small" bordered single-line :style="{ fontSize: '11px' }">
                  <thead>
                    <tr>
                      <th style="width: 20px; text-align: center;">#</th>
                      <th>因子</th>
                      <th style="width: 34px; text-align: center;">得分</th>
                      <th>条件</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(f, i) in getLogic(meta.name)!.short.entry" :key="'se'+i">
                      <td style="text-align: center; color: #8b8f97;">{{ i+1 }}</td>
                      <td>{{ f.name }}</td>
                      <td style="text-align: center;">
                        <span v-if="f.score" style="display:inline-block; padding:0 3px; background:#f0a020; color:#fff; font-weight:700; font-size:10px; border-radius:2px;">{{ f.score }}</span>
                      </td>
                      <td>{{ f.detail }}</td>
                    </tr>
                  </tbody>
                </n-table>
                <n-table size="small" bordered single-line :style="{ fontSize: '10px' }" style="margin-top: 3px;">
                  <thead>
                    <tr>
                      <th style="width:16px;text-align:center;">#</th>
                      <th>出场方式</th>
                      <th>正常模式</th>
                      <th v-if="getLogic(meta.name)!.exitWiden" style="text-align:center;">加宽</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(ex, i) in getLogic(meta.name)!.short.exit" :key="'sx'+i">
                      <td style="text-align:center;color:#8b8f97;">{{ i+1 }}</td>
                      <td>{{ ex.method }}</td>
                      <td>{{ ex.normal }}</td>
                      <td v-if="getLogic(meta.name)!.exitWiden" style="text-align:center;">{{ ex.widen || '—' }}</td>
                    </tr>
                  </tbody>
                </n-table>
                <div v-if="getLogic(meta.name)!.exitNote" style="font-size:10px;color:#8b8f97;margin-top:2px;">
                  {{ getLogic(meta.name)!.exitNote }}
                </div>
              </div>
            </div>
          </template>
          <div v-else style="font-size:12px; color:#8b8f97; padding:4px 0;">暂无详细策略说明</div>
        </div>
      </n-card>

      <n-button type="primary" :loading="saving" @click="save" block size="large"
        :disabled="loading">
        保存策略配置
      </n-button>
    </n-spin>
  </n-space>
</template>
