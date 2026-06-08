<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useSignalStore } from '@/stores/signals'
import { usePriceStore } from '@/stores/prices'
import { useConfigStore } from '@/stores/config'

const signalStore = useSignalStore()
const priceStore = usePriceStore()
const configStore = useConfigStore()

// ── News calendar ──

interface NewsEvent {
  title: string
  country: string
  impact: string
  datetime: string
  forecast: string
  previous: string
}

interface CalendarData {
  is_blackout: boolean
  blackout_reason: string
  upcoming_events: NewsEvent[]
  blackout_windows: Array<{ start: string; end: string; title: string }>
}

const calendarData = ref<CalendarData | null>(null)
const loadingNews = ref(false)
const newsExpanded = ref(false)
let refreshTimer: number | null = null

async function fetchCalendar() {
  loadingNews.value = true
  try {
    const res = await fetch('/api/news/calendar')
    if (res.ok) calendarData.value = await res.json()
  } catch (e) {
    console.error('新闻日历获取失败', e)
  } finally {
    loadingNews.value = false
  }
}

const nextEvent = computed(() => calendarData.value?.upcoming_events?.[0] ?? null)

// 财经事件中文名映射
const eventCN: Record<string, string> = {
  'CPI': '消费者物价指数',
  'CPI m/m': '消费者物价指数月率',
  'CPI y/y': '消费者物价指数年率',
  'Core CPI': '核心消费者物价指数',
  'Core CPI m/m': '核心消费者物价指数月率',
  'PPI': '生产者物价指数',
  'PPI m/m': '生产者物价指数月率',
  'Non-Farm Employment Change': '非农就业人数',
  'Unemployment Rate': '失业率',
  'Average Hourly Earnings m/m': '平均时薪月率',
  'Employment Change': '就业人数变化',
  'GDP': '国内生产总值',
  'GDP q/q': 'GDP季率',
  'GDP y/y': 'GDP年率',
  'Final GDP q/q': 'GDP终值季率',
  'GDP Price Index q/q': 'GDP平减指数季率',
  'Retail Sales': '零售销售',
  'Retail Sales m/m': '零售销售月率',
  'Core Retail Sales m/m': '核心零售销售月率',
  'Industrial Production': '工业生产',
  'Industrial Production m/m': '工业生产月率',
  'Capacity Utilization Rate': '产能利用率',
  'Manufacturing Production m/m': '制造业生产月率',
  'Building Permits': '营建许可',
  'Building Permits m/m': '营建许可月率',
  'Housing Starts': '新屋开工',
  'Housing Starts m/m': '新屋开工月率',
  'Existing Home Sales': '成屋销售',
  'New Home Sales': '新屋销售',
  'CB Consumer Confidence': '消费者信心指数',
  'Michigan Consumer Sentiment': '密歇根消费者信心指数',
  'Michigan 1-Year Inflation Expectations': '密歇根1年通胀预期',
  'ISM Manufacturing PMI': 'ISM制造业PMI',
  'ISM Non-Manufacturing PMI': 'ISM非制造业PMI',
  'ISM Services PMI': 'ISM服务业PMI',
  'Manufacturing PMI': '制造业PMI',
  'Services PMI': '服务业PMI',
  'Composite PMI': '综合PMI',
  'S&P Global Manufacturing PMI': '标普全球制造业PMI',
  'S&P Global Services PMI': '标普全球服务业PMI',
  'S&P Global Composite PMI': '标普全球综合PMI',
  'Philly Fed Manufacturing Index': '费城联储制造业指数',
  'Empire State Manufacturing Index': '纽约联储制造业指数',
  'Durable Goods Orders': '耐用品订单',
  'Durable Goods Orders m/m': '耐用品订单月率',
  'Core Durable Goods Orders m/m': '核心耐用品订单月率',
  'Factory Orders m/m': '工厂订单月率',
  'Business Inventories m/m': '商业库存月率',
  'Wholesale Inventories m/m': '批发库存月率',
  'Trade Balance': '贸易帐',
  'Import Prices m/m': '进口物价指数月率',
  'Export Prices m/m': '出口物价指数月率',
  'JOLTS Job Openings': 'JOLTS职位空缺',
  'ADP Non-Farm Employment Change': 'ADP就业人数',
  'Initial Jobless Claims': '初请失业金人数',
  'Continuing Jobless Claims': '续请失业金人数',
  '4-Week Moving Average': '四周均值',
  'Treasury Budget': '联邦预算',
  'Federal Budget Balance': '联邦预算平衡',
  'Consumer Credit m/m': '消费者信贷月率',
  'Personal Spending m/m': '个人支出月率',
  'Personal Income m/m': '个人收入月率',
  'PCE Price Index m/m': 'PCE物价指数月率',
  'PCE Price Index y/y': 'PCE物价指数年率',
  'Core PCE Price Index m/m': '核心PCE物价指数月率',
  'Core PCE Price Index y/y': '核心PCE物价指数年率',
  'FOMC Statement': 'FOMC声明',
  'FOMC Meeting Minutes': 'FOMC会议纪要',
  'FOMC Press Conference': 'FOMC新闻发布会',
  'Federal Funds Rate': '联邦基金利率',
  'Consumer Inflation Expectations': '消费者通胀预期',
  'Inflation Expectations': '通胀预期',
  '10-y Bond Auction': '10年期国债拍卖',
  '30-y Bond Auction': '30年期国债拍卖',
  '5-y Note Auction': '5年期国债拍卖',
  '7-y Note Auction': '7年期国债拍卖',
  '2-y Note Auction': '2年期国债拍卖',
  'Current Account': '经常帐',
  'Hourly Wage Index': '时薪指数',
  'Labor Cost Index q/q': '劳动力成本指数季率',
  'Labor Productivity q/q': '劳动生产率季率',
  'Unit Labor Costs q/q': '单位劳动力成本季率',
  'Chicago PMI': '芝加哥PMI',
  'Dallas Fed Manufacturing Index': '达拉斯联储制造业指数',
  'Richmond Fed Manufacturing Index': '里士满联储制造业指数',
  'Kansas City Fed Manufacturing Index': '堪萨斯联储制造业指数',
  'Home Price Index m/m': '房价指数月率',
  'House Price Index y/y': '房价指数年率',
  'S&P/CS Composite-20 HPI y/y': '标普/Case-Shiller房价指数年率',
  'NAHB Housing Market Index': 'NAHB房产市场指数',
  'MBA Mortgage Applications': 'MBA抵押贷款申请',
  'MBA Mortgage Applications w/w': 'MBA抵押贷款申请周率',
  'EIA Crude Oil Stocks Change': 'EIA原油库存变化',
  'Crude Oil Inventories': '原油库存',
  'Cushing Crude Oil Inventories': '库欣原油库存',
  'Gasoline Production': '汽油产量',
  'Distillate Fuel Production': '馏分油产量',
  'Natural Gas Storage': '天然气库存',
  'Baker Hughes Oil Rig Count': '贝克休斯石油钻井数',
  'Fed Chair Powell Speech': '鲍威尔讲话',
  'Fed Monetary Policy Report': '美联储货币政策报告',
  'Fed Interest Rate Decision': '美联储利率决议',
}

function evtName(title: string) {
  const cn = eventCN[title] || ''
  return cn ? `${cn}（${title}）` : title
}

const activeStrategies = computed(() => {
  const pool = configStore.items.strategy_pool || {}
  return Object.entries(pool)
    .filter(([, cfg]: [string, any]) => cfg.enabled !== false)
    .map(([name, cfg]: [string, any]) => ({
      name,
      magic: cfg.magic || 0,
      timeframe: cfg.timeframe || 'H1',
    }))
})

// 策略颜色（与持仓表一致，按 magic 固定）
const strategyColors: Record<string, string> = {
  'H1_v6_hybrid': '#2080f0',
  'M30_rsi_bb': '#f0a020',
  'sanqing_h1': '#9220f0',
  'gold_auto_research': '#20c080',
  'bakome_backup': '#808080',
  'xaubot_backup': '#808080',
}

const strategyLogics: Record<string, { factors: string[]; desc: string }> = {
  H1_v6_hybrid: {
    desc: '多因子评分（≥5分开多，≥3分开空）',
    factors: [
      '① SMA200 趋势：收盘价 > SMA200 → +1',
      '② KDJ 超卖：K < 30(超卖) → +1',
      '③ 布林下轨：最低价 ≤ 布林下轨 → +1',
      '④ Keltner 下轨：最低价 ≤ Keltner 下轨 → +1',
      '⑤ MACD 底背离：价格新低 + MACD 抬升 → +2',
      '⑥ RSI 超卖：RSI < 30 → +1',
      '⑦ 低波动：ATR < SMA(ATR)×1.2 → +1',
      '⑧ M30 方向：M30 EMA20 升/降 → ±1',
    ],
  },
  M30_rsi_bb: {
    desc: 'RSI 超卖/超买 + 布林带触碰',
    factors: [
      '① RSI < 30 超卖 + 收盘价 ≤ 布林下轨 → BUY',
      '② RSI > 70 超买 + 收盘价 ≥ 布林上轨 → SELL',
      '③ EMA20 跟踪止损：突破均线反向 → 平仓',
      '④ M30 周期，适合短线震荡行情',
    ],
  },
  sanqing_h1: {
    desc: '三清共振：趋势 + 动量 + 波动率',
    factors: [
      '① SMA50/200 趋势过滤：多头/空头排列',
      '② MACD 金叉/死叉 + 柱体确认动量',
      '③ ATR 波动率过滤：避免低波动假突破',
      '④ H1 周期，适合日内波段交易',
    ],
  },
  gold_auto_research: {
    desc: '黄金自动研究：多指标综合判断',
    factors: [
      '① KDJ 超卖/超买区域判断',
      '② 布林带上下轨支撑阻力',
      '③ 价格 vs SMA200 大趋势方向',
      '④ H1 周期，综合型交易策略',
    ],
  },
}

const expandedStratKeys = ref<string[]>([])

function impactColor(impact: string) {
  return impact === 'High' ? '#f6465d' : impact === 'Medium' ? '#f0a020' : '#8b8f97'
}

onMounted(() => {
  configStore.fetch()
  fetchCalendar()
  refreshTimer = window.setInterval(fetchCalendar, 300000)
})

onUnmounted(() => {
  if (refreshTimer !== null) clearInterval(refreshTimer)
})
</script>

<template>
  <n-space vertical size="small">

    <!-- ═══════════════ 实盘信号 ═══════════════ -->
    <n-card size="small" :bordered="true"
      :style="{
        borderLeft: `4px solid ${
          signalStore.signal === 'BUY' ? '#0ecb81'
          : signalStore.signal === 'SELL' ? '#f6465d'
          : '#8b8f97'
        }`,
      }">
      <n-space vertical>
        <!-- 信号指示：仅在有信号时显示 -->
        <div v-if="signalStore.signal" style="text-align: center; padding: 4px 0 8px;">
          <n-h2 style="margin: 0;" prefix="bar">
            <n-text
              :type="signalStore.signal === 'BUY' ? 'success' : 'error'"
              style="font-size: 28px; font-weight: 700; letter-spacing: 2px;">
              <span v-if="signalStore.signal === 'BUY'" style="color: #0ecb81;">▲ BUY</span>
              <span v-else style="color: #f6465d;">▼ SELL</span>
            </n-text>
          </n-h2>
          <n-text v-if="signalStore.timestamp" depth="3" style="font-size: 12px;">
            {{ signalStore.timestamp }}
          </n-text>
        </div>

        <!-- 报价：一行显示，统一格式 -->
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 0;">
          <span style="font-size: 15px; font-weight: 600;">现价 {{ priceStore.midPrice.toFixed(2) }}</span>
          <span style="font-size: 15px; font-weight: 600;">Bid {{ priceStore.bid.toFixed(2) }} / Ask {{ priceStore.ask.toFixed(2) }}</span>
          <span style="font-size: 15px; font-weight: 600;">点差 {{ priceStore.spread.toFixed(2) }}</span>
        </div>
      </n-space>
    </n-card>

    <!-- ═══════════════ 新闻日历 ═══════════════ -->
    <n-card title="新闻日历" size="small" :bordered="true"
      :segmented="{ content: true }"
      :style="{
        borderLeft: `4px solid ${
          calendarData?.is_blackout ? '#f6465d' : '#8b8f97'
        }`,
      }">
      <template #header-extra>
        <n-button size="tiny" text
          style="font-size: 20px; font-weight: 700; color: #8b8f97; cursor: pointer;"
          @click="newsExpanded = !newsExpanded">
          {{ newsExpanded ? '−' : '+' }}
        </n-button>
      </template>

      <n-space vertical size="small">
        <!-- 状态 + 下一事件 -->
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <n-space align="center" size="small">
            <n-tag
              v-if="calendarData?.is_blackout"
              type="error" size="tiny" :bordered="false">禁售中</n-tag>
            <n-tag v-else size="tiny" :bordered="false"
              style="background: #8b8f9720; color: #8b8f97;">正常交易</n-tag>
            <n-text v-if="calendarData?.is_blackout" depth="2" style="font-size: 12px;">
              {{ calendarData.blackout_reason }}
            </n-text>
          </n-space>
          <n-text v-if="calendarData?.upcoming_events?.length" depth="3" style="font-size: 11px;">
            待 {{ calendarData.upcoming_events.length }} 事件
          </n-text>
        </div>

        <!-- 下一事件 -->
        <div v-if="nextEvent" :style="{
          padding: '6px 10px', borderRadius: '4px',
          background: calendarData?.is_blackout ? '#f6465d10' : 'var(--n-color-embedded)',
        }">
          <n-text depth="3" style="font-size: 10px;">下一事件</n-text>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 2px;">
            <n-text style="font-size: 13px; font-weight: 600;">{{ evtName(nextEvent.title) }}</n-text>
            <n-tag size="tiny" :color="{ color: impactColor(nextEvent.impact) }" text-color="#fff">
              {{ nextEvent.impact }}
            </n-tag>
          </div>
          <div style="display: flex; justify-content: space-between; margin-top: 4px;">
            <n-text depth="3" style="font-size: 11px;">{{ nextEvent.datetime }}</n-text>
            <n-text depth="3" style="font-size: 11px;">
              {{ nextEvent.previous ? '前值 ' + nextEvent.previous : '' }}
              {{ nextEvent.forecast ? ' | 预测 ' + nextEvent.forecast : '' }}
            </n-text>
          </div>
        </div>

        <!-- 展开日历列表 -->
        <n-collapse-transition :show="newsExpanded">
          <n-space vertical size="small">
            <div v-for="evt in calendarData?.upcoming_events" :key="evt.datetime + evt.title"
              :style="{
                padding: '8px 10px', borderRadius: '4px',
                background: 'var(--n-color-embedded)',
              }">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <n-text style="font-size: 12px; font-weight: 600;">{{ evtName(evt.title) }}</n-text>
                <n-tag size="tiny" :color="{ color: impactColor(evt.impact) }" text-color="#fff">
                  {{ evt.impact }}
                </n-tag>
              </div>
              <div style="display: flex; justify-content: space-between; margin-top: 4px;">
                <n-text depth="3" style="font-size: 11px;">{{ evt.datetime }}</n-text>
                <n-text depth="3" style="font-size: 11px;">
                  前值 {{ evt.previous || '-' }} | 预测 {{ evt.forecast || '-' }}
                </n-text>
              </div>
            </div>
            <div v-if="!calendarData?.upcoming_events?.length" style="text-align: center; padding: 8px;">
              <n-empty description="暂无高影响事件" />
            </div>
          </n-space>
        </n-collapse-transition>
      </n-space>
    </n-card>

    <!-- ═══════════════ 实盘策略 ═══════════════ -->
    <n-card size="small" :bordered="true">
      <n-collapse :expanded-names="expandedStratKeys" @update:expanded-names="expandedStratKeys = $event">
        <n-collapse-item v-for="s in activeStrategies" :key="s.name" :name="s.name"
          :style="{ borderLeft: `3px solid ${strategyColors[s.name] || '#808080'}`,
                   marginBottom: '4px', borderRadius: '4px' }">
          <template #header>
            <n-space align="center" size="small">
              <n-tag :color="{ color: strategyColors[s.name] || '#808080' }" size="tiny" text-color="#fff">
                {{ s.name }}
              </n-tag>
              <n-text depth="3" style="font-size: 11px;">TF:{{ s.timeframe }}</n-text>
              <n-text depth="3" style="font-size: 11px;">M:{{ s.magic }}</n-text>
            </n-space>
          </template>
          <n-text depth="2" style="font-size: 12px; display: block; margin-bottom: 6px;">
            {{ strategyLogics[s.name]?.desc || '' }}
          </n-text>
          <div v-for="(f, fi) in strategyLogics[s.name]?.factors || []" :key="fi"
            style="font-size: 11px; color: #8b8f97; padding: 2px 0;">
            {{ f }}
          </div>
        </n-collapse-item>
        <n-empty v-if="!activeStrategies.length" description="暂无运行策略" />
      </n-collapse>
    </n-card>
  </n-space>
</template>
