<script setup lang="ts">
import { h, ref, computed, onMounted, watch, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTradeStore } from '@/stores/trades'
import { getTradeStats, getTradeAnalysis } from '@/api/client'
import type { TradeStats } from '@/types'
import { NTag, NButton, NDataTable, NEmpty, NSkeleton, NAlert, NSpace, NTabs, NTabPane, NGrid, NGi, NStatistic, NCard, NSelect, NDatePicker, NIcon, NSpin, NInput, NModal, NProgress } from 'naive-ui'
import { SearchOutline } from '@vicons/ionicons5'
import StrategyRadar from '@/components/dashboard/StrategyRadar.vue'
import { getSignals } from '@/api/client'

const { t } = useI18n()
const store = useTradeStore()
const refreshLoading = ref(false)
const activeTab = ref('history')

// ── 搜索过滤 ──
const searchQuery = ref('')
const filteredData = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return store.items
  return store.items.filter((t: any) =>
    (t.strategy && t.strategy.toLowerCase().includes(q)) ||
    (t.magic && t.magic.toString().includes(q)) ||
    (t.ticket && t.ticket.toString().includes(q))
  )
})

// 全部成交的总盈亏
const totalPnl = computed(() => {
  return store.items.reduce((sum: number, t: any) => sum + (Number(t.pnl) || 0), 0)
})

// ── 成交明细标签页（原代码）────────────────────────────

onMounted(() => store.fetch())

async function refresh() {
  refreshLoading.value = true
  await store.fetch()
  if (activeTab.value === 'stats') await loadStats()
  refreshLoading.value = false
}

// ── 展开行分析 ──
const expandedRowKeys = ref<(string | number)[]>([])
const analysisCache = reactive<Record<number, any>>({})
const analysisLoading = reactive<Record<number, boolean>>({})

async function onExpand(ticket: number) {
  if (analysisCache[ticket]) return
  analysisLoading[ticket] = true
  try {
    const result = await getTradeAnalysis(ticket)
    analysisCache[ticket] = result
  } catch (e: any) {
    analysisCache[ticket] = { error: e?.message || t('trades.analysis_fail') }
  } finally {
    analysisLoading[ticket] = false
  }
}

function renderAnalysis(row: any) {
  const ticket = row.ticket
  if (analysisLoading[ticket]) {
    return h(NSpin, {}, { default: () => t('trades.analysis_loading') })
  }
  const data = analysisCache[ticket]
  if (!data) return h('span', t('trades.analysis_click'))
  if (data.error) return h('span', { style: { color: '#f6465d' } }, t('trades.analysis_error', { error: data.error }))

  const sec = (s: number) => s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s/60)}m` : `${(s/3600).toFixed(1)}h`

  return h('div', { style: 'padding: 12px 24px; font-size: 13px; line-height: 1.6;' }, [
    h('div', { style: 'display: grid; grid-template-columns: 1fr 1fr; gap: 16px;' }, [
      // 左列：开仓分析
      h('div', {}, [
        h('div', { style: 'font-weight: 700; margin-bottom: 8px; color: #0ecb81;' }, t('trades.entry_logic')),
        h('div', {}, `系统: ${data.entry_analysis?.system || t('trades.unknown')}`),
        data.entry_analysis?.likely_conditions?.length
          ? h('div', { style: 'margin-top: 4px;' }, [
              h('span', { style: 'color: #888;' }, t('trades.trigger_condition')),
              ...data.entry_analysis.likely_conditions.map((c: string, i: number) =>
                h('span', { style: 'background: #1a1a2e; padding: 1px 6px; border-radius: 3px; margin-right: 4px;' }, c)
              ),
            ])
          : null,
        data.entry_analysis?.factors
          ? h('div', { style: 'margin-top: 8px;' }, [
              h('div', { style: 'color: #888; margin-bottom: 4px;' }, t('trades.score_factors')),
              ...data.entry_analysis.factors.map((f: any) =>
                h('div', { style: 'font-size: 12px; padding: 2px 0;' }, `• ${f.name}: ${f.desc}`)
              ),
            ])
          : null,
      ]),
      // 右列：平仓分析
      h('div', {}, [
        h('div', { style: 'font-weight: 700; margin-bottom: 8px; color: #f6465d;' }, t('trades.exit_logic')),
        h('div', {}, `方式: ${data.exit_analysis?.label || t('trades.unknown')}`),
        h('div', { style: 'margin-top: 4px;' }, `逻辑: ${data.exit_analysis?.logic || t('trades.exit_none')}`),
        data.exit_analysis?.is_loss
          ? h('div', { style: 'margin-top: 12px;' }, [
              h('div', { style: 'font-weight: 700; color: #f0a020; margin-bottom: 6px;' }, t('trades.loss_analysis')),
              ...(data.exit_analysis?.loss_analysis?.possible_reasons || []).map((r: string) =>
                h('div', { style: 'font-size: 12px; padding: 2px 0;' }, `• ${r}`)
              ),
              ...(data.exit_analysis?.loss_analysis?.suggestions || []).map((s: string) =>
                h('div', { style: 'font-size: 12px; padding: 2px 0; color: #7cb8ff;' }, `→ ${s.replace(/\\n/g, ' ')}`)
              ),
            ])
          : h('div', { style: 'margin-top: 8px; color: #0ecb81;' }, t('trades.profit_trade')),
      ]),
    ]),
  ])
}

const exitReasonLabels: Record<string, string> = {
  'strategy_exit': t('trades.exit_strategy'),
  'mt4_history': t('trades.exit_mt4'),
  'stop_loss': t('trades.exit_stop'),
  'take_profit': t('trades.exit_tp'),
}

const columns = [
  {
    type: 'expand' as const,
    width: 30,
    renderExpand: (row: any) => renderAnalysis(row),
  },
  { title: 'Ticket', key: 'ticket', width: 80, sortable: true, sorter: (a: any, b: any) => a.ticket - b.ticket },
  { title: t('trades.strategy'), key: 'strategy', width: 160, sortable: true,
    render(row: any) {
      return h(NTag, { size: 'small', type: row.strategy?.includes('stoch') ? 'info' : 'warning' },
        { default: () => row.strategy }
      )
    }
  },
  {
    title: 'TF', key: 'timeframe', width: 50, sortable: true,
    render(row: any) {
      const s = row.strategy?.toLowerCase() || ''
      if (s.includes('h4')) return 'H4'
      if (s.includes('h1')) return 'H1'
      if (s.includes('m30')) return 'M30'
      if (s.includes('m15')) return 'M15'
      if (s.includes('m5')) return 'M5'
      return row.timeframe || ''
    }
  },
  {
    title: t('trades.direction'), key: 'order_type', width: 40, sortable: true,
    render(row: any) {
      const isBuy = row.order_type?.includes('BUY')
      return h(NTag, { type: isBuy ? 'success' : 'error', size: 'tiny' },
        { default: () => isBuy ? t('trades.long') : t('trades.short') }
      )
    }
  },
  { title: t('trades.volume'), key: 'volume', width: 40, sortable: true },
  { title: t('trades.open_price'), key: 'entry_price', width: 100, sortable: true,
    render(row: any) { return row.entry_price?.toFixed(2) }
  },
  { title: t('trades.close_price'), key: 'exit_price', width: 100, sortable: true,
    render(row: any) { return row.exit_price?.toFixed(2) }
  },
  {
    title: t('trades.profit'), key: 'pnl', width: 100, sortable: true,
    render(row: any) {
      const val = row.pnl ?? 0
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  {
    title: t('trades.profit_commission'), key: 'net_pnl', width: 100,
    render(row: any) {
      const val = (row.pnl ?? 0) + (row.swap ?? 0) + (row.commission ?? 0)
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  { title: t('trades.duration'), key: 'hold_seconds', width: 90,
    render(row: any) {
      const sec = row.hold_seconds ?? 0
      if (sec < 60) return `${sec}s`
      if (sec < 3600) return `${Math.round(sec / 60)}m`
      return `${(sec / 3600).toFixed(1)}h`
    }
  },
  { title: t('trades.exit_reason'), key: 'exit_reason', width: 100,
    render(row: any) {
      const reason = row.exit_reason || ''
      const label = exitReasonLabels[reason] || reason || '-'
      const type = reason === 'stop_loss' ? 'error' : reason === 'take_profit' ? 'success' : 'default'
      return h(NTag, { size: 'small', type }, { default: () => label })
    }
  },
  { title: t('trades.open_time'), key: 'open_time', width: 150 },
  { title: t('trades.close_time'), key: 'close_time', width: 150 },
]

// ── 策略统计标签页 ──────────────────────────────────────

const statsData = ref<TradeStats | null>(null)
const statsLoading = ref(false)
const statsError = ref<string | null>(null)
const selectedStrategy = ref('')
const selectedVersion = ref('')

// 筛选器
const selectedStrategies = ref<string[]>([])
const dateRange = ref<[number, number] | null>(null)

const strategyOptions = computed(() => {
  const names = [...new Set(store.items.map((t: any) => t.strategy).filter(Boolean))]
  return names.map(n => ({ label: n, value: n }))
})

function fmtDate(ts: number): string {
  return new Date(ts).toISOString().slice(0, 10)
}

async function loadStats() {
  statsLoading.value = true
  statsError.value = null
  try {
    const params: Record<string, string> = {}
    if (selectedStrategies.value.length) params.strategies = selectedStrategies.value.join(',')
    if (dateRange.value) {
      params.from_date = fmtDate(dateRange.value[0])
      params.to_date = fmtDate(dateRange.value[1])
    }
    statsData.value = await getTradeStats(params)
    // 默认选中第一个策略
    if (!selectedStrategy.value) {
      const by = statsData.value?.by_strategy || {}
      const entries = Object.entries(by)
      if (entries.length) selectedStrategy.value = entries[0][0]
    }
  } catch (e: any) {
    statsError.value = e?.message || t('trades.stats_fail')
  } finally {
    statsLoading.value = false
  }
}

// 废票数据
const voidedSignals = ref<any[]>([])
const voidedLoading = ref(false)
const voidedExpandedKeys = ref<(string | number)[]>([])

const voidedColumns = [
  { type: 'expand', width: 35, renderExpand: (row: any) => {
    const fl = row.factors_long ? JSON.parse(row.factors_long) : []
    const fs = row.factors_short ? JSON.parse(row.factors_short) : []
    let iv: Record<string, any> = {}
    try { iv = row.indicator_values ? JSON.parse(row.indicator_values) : {} } catch {}
    const ivEntries = Object.entries(iv).filter(([k]) => !['recent_high','recent_low','price_position'].includes(k))
    const importantKeys = ['rsi','atr','close','ema9','ema21','adx','macd_val']
    return h('div', { style: 'padding: 8px 20px; font-size: 13px;' }, [
      h('div', { style: 'display: grid; grid-template-columns: 1fr 1.5fr; gap: 8px;' }, [
        h('div', {}, [
          h('div', { style: 'font-weight:700;color:#0ecb81;margin-bottom:2px;' }, t('trades.void_long_factors')),
          h('div', { style: 'font-size:13px;' }, fl.length ? fl.join(' → ') : t('trades.exit_none')),
          h('div', { style: 'font-weight:700;color:#f6465d;margin:6px 0 2px;' }, t('trades.void_short_factors')),
          h('div', { style: 'font-size:13px;' }, fs.length ? fs.join(' → ') : t('trades.exit_none')),
          h('div', { style: 'margin-top:6px;font-weight:700;' }, t('trades.void_score', { long: row.score_long, short: row.score_short })),
        ]),
        h('div', {}, [
          h('div', { style: 'font-weight:700;margin-bottom:2px;' }, t('trades.void_snapshot')),
          h('div', { style: 'display:grid; grid-template-columns:repeat(3,1fr); gap:3px;' },
            ivEntries.map(([k, v]) =>
              h('div', {
                style: `background:#1a1a2e;padding:2px 6px;border-radius:3px;font-size:12px;${importantKeys.includes(k) ? 'font-weight:700;color:#f0e68c;' : ''}`
              }, `${k}=${typeof v === 'number' ? v.toFixed(2) : v}`)
            )
          ),
        ]),
      ]),
    ])
  }},
  { title: t('trades.void_signal_id'), key: 'id', width: 70 },
  { title: t('trades.strategy'), key: 'strategy', width: 100 },
  { title: 'TF', key: 'timeframe', width: 50,
    render(row: any) {
      const s = row.strategy?.toLowerCase() || ''
      if (s.includes('h4')) return 'H4'
      if (s.includes('h1')) return 'H1'
      if (s.includes('m30')) return 'M30'
      if (s.includes('m15')) return 'M15'
      if (s.includes('m5')) return 'M5'
      // 策略名无时间后缀时的 fallback 映射
      const tfMap: Record<string, string> = { 'gold_auto_research': 'H1', 'h1_breakout': 'H1' }
      return tfMap[s] || row.timeframe || ''
    }
  },
  { title: t('trades.direction'), key: 'signal', width: 60,
    render(row: any) { return h('span', { style: { color: row.signal?.includes('BUY') ? '#0ecb81' : '#f6465d' } }, row.signal) }
  },
  { title: t('trades.void_time'), key: 'timestamp', width: 150 },
  { title: t('trades.void_reason'), key: 'void_reason', width: 120 },
]

async function loadVoided() {
  voidedLoading.value = true
  try {
    voidedSignals.value = await getSignals({ status: 'voided', limit: 200 })
  } catch { voidedSignals.value = [] }
  finally { voidedLoading.value = false }
}

watch(activeTab, (tab) => {
  if (tab === 'stats' && !statsData.value) loadStats()
  if (tab === 'voided') loadVoided()
})

// 展开行时自动请求分析
watch(expandedRowKeys, (keys, oldKeys) => {
  if (!oldKeys) { keys.forEach(k => onExpand(k as number)); return }
  const oldSet = new Set(oldKeys)
  keys.forEach(k => { if (!oldSet.has(k)) onExpand(k as number) })
})

// 汇总指标卡片
const summaryCards = computed(() => {
  const s = statsData.value?.summary
  if (!s) return []
  return [
    { label: t('trades.total_pnl'), value: s.total_net_profit, fmt: (v: any) => `${v >= 0 ? '+' : ''}$${Number(v).toFixed(2)}`, color: s.total_net_profit >= 0 ? '#0ecb81' : '#f6465d' },
    { label: 'Profit Factor', value: s.profit_factor, fmt: (v: any) => v, color: undefined },
    { label: t('trades.total_trades'), value: s.total_trades, fmt: (v: any) => String(v), color: undefined },
    { label: t('trades.win_rate'), value: s.win_rate, fmt: (v: any) => `${v}%`, color: s.win_rate >= 50 ? '#0ecb81' : '#f6465d' },
    { label: 'Expected Payoff', value: s.expected_payoff, fmt: (v: any) => `${v >= 0 ? '+' : ''}$${Number(v).toFixed(2)}`, color: s.expected_payoff >= 0 ? '#0ecb81' : '#f6465d' },
    { label: t('trades.max_consec_loss'), value: s.max_consecutive_losses, fmt: (v: any) => `${v} ${t('trades.times')}`, color: undefined },
  ]
})

// 分策略透视表（按策略族分组，4位PPNN）
const statsExpandedRowKeys = ref<string[]>([])

function renderStatsExpand(row: any) {
  if (!row.versions?.length) return t('trades.no_version_detail')
  const cols = [
    { title: 'Magic', key: 'magic' },
    { title: t('trades.version'), key: 'version' },
    { title: t('trades.total_pnl'), key: 'total_net_profit', render(r: any) {
      const v = r.total_net_profit ?? 0
      return h('span', { style: { color: v >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`)
    }},
    { title: t('trades.trade_count'), key: 'total_trades' },
    { title: t('trades.win_rate'), key: 'win_rate', render(r: any) { return `${r.win_rate}%` }},
    { title: 'PF', key: 'profit_factor', render(r: any) { return r.profit_factor }},
    { title: t('trades.avg_profit_label'), key: 'avg_profit_trade', render(r: any) { return `$${r.avg_profit_trade?.toFixed(2)}` }},
    { title: t('trades.avg_loss_label'), key: 'avg_loss_trade', render(r: any) { return `$${r.avg_loss_trade?.toFixed(2)}` }},
  ]
  return h('div', { style: 'padding: 8px 24px;' }, [
    h(NDataTable, {
      columns: cols,
      data: row.versions,
      size: 'small',
      bordered: false,
      striped: true,
      'single-line': false,
      maxHeight: 400,
    })
  ])
}

const statsTableData = computed(() => {
  const by = statsData.value?.by_strategy || {}
  return Object.entries(by).map(([name, s]: [string, any]) => ({
    ...s,
    strategy: name,
    key: name,
  })) as any[]
})

const statsColumns = [
  {
    type: 'expand' as const,
    width: 40,
    renderExpand: renderStatsExpand,
  },
  { title: 'Magic', key: 'magic', width: 70, fixed: 'left' as const },
  {
    title: t('trades.strategy'), key: 'strategy', width: 130,
    render(row: any) {
      return h(NTag, { size: 'small', type: row.strategy?.includes('stoch') ? 'info' : 'warning' },
        { default: () => row.strategy }
      )
    }
  },
  { title: t('trades.total_pnl'), key: 'total_net_profit', width: 100, sortable: true,
    render(row: any) {
      const v = row.total_net_profit ?? 0
      return h('span', { style: { color: v >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`
      )
    }
  },
  { title: t('trades.gross_profit'), key: 'gross_profit', width: 90,
    render(row: any) { return h('span', { style: { color: '#0ecb81' } }, `$${row.gross_profit?.toFixed(2)}`) }
  },
  { title: t('trades.gross_loss'), key: 'gross_loss', width: 90,
    render(row: any) { return h('span', { style: { color: '#f6465d' } }, `$${row.gross_loss?.toFixed(2)}`) }
  },
  { title: 'PF', key: 'profit_factor', width: 70,
    render(row: any) { return row.profit_factor }
  },
  { title: t('trades.total_trades'), key: 'total_trades', width: 70, sortable: true },
  {
    title: t('trades.long_win_rate'), key: 'long_won_pct', width: 90,
    render(row: any) { return `${row.long_trades} (${row.long_won_pct}%)` }
  },
  {
    title: t('trades.short_win_rate'), key: 'short_won_pct', width: 90,
    render(row: any) { return `${row.short_trades} (${row.short_won_pct}%)` }
  },
  { title: t('trades.total_win_rate'), key: 'win_rate', width: 70,
    render(row: any) { return `${row.win_rate}%` }
  },
  {
    title: t('trades.avg_profit_label'), key: 'avg_profit_trade', width: 90,
    render(row: any) { return `$${row.avg_profit_trade?.toFixed(2)}` }
  },
  {
    title: t('trades.avg_loss_label'), key: 'avg_loss_trade', width: 90,
    render(row: any) { return `$${row.avg_loss_trade?.toFixed(2)}` }
  },
  { title: t('trades.profit_loss_ratio'), key: 'ratio_avg_profit_loss', width: 90 },
  {
    title: t('trades.max_profit'), key: 'largest_profit_trade', width: 90,
    render(row: any) { return `$${row.largest_profit_trade?.toFixed(2)}` }
  },
  {
    title: t('trades.max_loss'), key: 'largest_loss_trade', width: 90,
    render(row: any) { return `$${row.largest_loss_trade?.toFixed(2)}` }
  },
  { title: t('trades.avg_duration'), key: 'avg_hold_seconds', width: 80,
    render(row: any) {
      const sec = row.avg_hold_seconds ?? 0
      if (sec < 60) return `${sec}s`
      if (sec < 3600) return `${Math.round(sec / 60)}m`
      return `${(sec / 3600).toFixed(1)}h`
    }
  },
  { title: t('trades.consec_win'), key: 'max_consecutive_wins', width: 80 },
  { title: t('trades.consec_loss'), key: 'max_consecutive_losses', width: 80 },
  { title: t('trades.consec_win_money'), key: 'max_consecutive_wins_pnl', width: 80,
    render(row: any) { return `$${row.max_consecutive_wins_pnl?.toFixed(2)}` }
  },
  { title: t('trades.consec_loss_money'), key: 'max_consecutive_losses_pnl', width: 80,
    render(row: any) { return `$${row.max_consecutive_losses_pnl?.toFixed(2)}` }
  },
]
</script>

<template>
  <n-space vertical size="large">
    <div class="history-header">
      <n-h2 class="history-title">{{ t('trades.title') }}</n-h2>
      <n-space size="small">
        <n-tag :bordered="false" type="info">{{ t('trades.total_count', { count: store.items.length }) }}</n-tag>
        <n-tag :bordered="false" :type="totalPnl >= 0 ? 'success' : 'error'">{{ t('trades.total_pnl') }}: {{ totalPnl >= 0 ? '+' : '' }}${{ Math.abs(totalPnl).toFixed(2) }}</n-tag>
        <n-button size="small" secondary :loading="refreshLoading" @click="refresh">
          {{ t('trades.refresh') }}
        </n-button>
      </n-space>
    </div>

    <n-tabs v-model:value="activeTab" type="line" animated>
    <!-- ═══ 成交明细 ═══ -->
      <n-tab-pane name="history" :tab="t('trades.detail_tab')">
        <n-space class="history-search-bar">
          <n-input v-model:value="searchQuery" :placeholder="t('trades.search')"
                   clearable class="search-input">
            <template #prefix>
              <n-icon :component="SearchOutline" />
            </template>
          </n-input>
          <n-tag :bordered="false" type="info">{{ t('trades.filtered_count', { count: filteredData.length }) }}</n-tag>
        </n-space>
        <n-data-table v-if="store.loading" :columns="columns" :data="[]" :loading="true" :bordered="true" :max-height="600" />
        <n-empty v-else-if="store.items.length === 0" :description="t('trades.empty')">
          <template #extra>
            <n-text depth="3">{{ t('trades.empty_hint') }}</n-text>
          </template>
        </n-empty>
        <n-alert v-else-if="store.error" type="error" :title="store.error" closable />
        <n-data-table v-else :columns="columns" :data="filteredData" :bordered="true"
                      :max-height="700" striped :single-line="false"
                      v-model:expanded-row-keys="expandedRowKeys"
                      :row-key="(row: any) => row.ticket" />
      </n-tab-pane>

      <!-- ═══ 策略统计 ═══ -->
      <n-tab-pane name="stats" :tab="t('trades.stats_tab')">
        <!-- 筛选栏 -->
        <n-card size="small" :bordered="true" class="stats-card">
          <n-space align="center" size="medium">
            <n-select v-if="strategyOptions.length"
              v-model:value="selectedStrategies" :options="strategyOptions"
              multiple clearable :placeholder="t('trades.filter_strategy')" class="filter-select" />
            <n-date-picker v-model:value="dateRange" type="daterange" clearable
              :placeholder="t('trades.date_range')" class="filter-datepicker" />
            <n-button type="primary" size="small" @click="loadStats" :loading="statsLoading">
              {{ t('trades.query') }}
            </n-button>
          </n-space>
        </n-card>

        <!-- 加载态 -->
        <template v-if="statsLoading">
          <n-card size="small">
            <n-space vertical size="medium">
              <n-skeleton text :repeat="3" />
              <n-skeleton text class="skeleton-short" />
            </n-space>
          </n-card>
        </template>

        <!-- 空态 -->
        <n-empty v-else-if="!statsData || statsData.summary.total_trades === 0" :description="t('trades.stats_empty')">
          <template #extra>
            <n-text depth="3">{{ t('trades.stats_hint') }}</n-text>
          </template>
        </n-empty>

        <!-- 错误态 -->
        <n-alert v-else-if="statsError" type="error" :title="statsError" closable />

        <!-- 数据态 -->
        <template v-else>
          <!-- 策略雷达评估 -->
          <StrategyRadar :stats="statsData" :selected-strategy="selectedStrategy"
            :selected-version="selectedVersion"
            @select="(v: string) => { selectedStrategy = v; selectedVersion = '' }"
            @select-version="(v: string) => selectedVersion = v" />

          <!-- 汇总指标卡片 -->
          <n-card size="small" :bordered="true" class="stats-card">
            <n-grid :cols="6" :x-gap="16" :y-gap="12">
              <n-gi v-for="card in summaryCards" :key="card.label">
                <n-statistic :label="card.label" tabular-nums>
                  <span v-if="card.color" :style="{ color: card.color, fontWeight: 700 }">
                    {{ card.fmt(card.value) }}
                  </span>
                  <span v-else>{{ card.fmt(card.value) }}</span>
                </n-statistic>
              </n-gi>
            </n-grid>
          </n-card>

          <!-- 分策略透视表 -->
          <n-card size="small" :bordered="true">
            <n-data-table :columns="statsColumns" :data="statsTableData" :bordered="true"
                          :max-height="600" striped :single-line="false" size="small"
                          :scroll-x="1600"
                          v-model:expanded-row-keys="statsExpandedRowKeys"
                          :row-key="(row: any) => row.key || row.strategy" />
          </n-card>
        </template>
      </n-tab-pane>

      <!-- 废票 -->
      <n-tab-pane name="voided" :tab="t('trades.voided_tab')">
        <n-space vertical size="small">
          <n-tag :bordered="false" type="warning">{{ t('trades.voided_count', { count: voidedSignals.length }) }}</n-tag>
          <n-data-table v-if="voidedLoading"
            :columns="voidedColumns" :data="[]" :loading="true" :bordered="true" :max-height="500" />
          <n-empty v-else-if="voidedSignals.length === 0" :description="t('trades.voided_empty')" />
          <n-data-table v-else :columns="voidedColumns" :data="voidedSignals" :bordered="true"
            :max-height="500" striped :single-line="false"
            v-model:expanded-row-keys="voidedExpandedKeys"
            :row-key="(row: any) => row.id" />
        </n-space>
      </n-tab-pane>
    </n-tabs>
  </n-space>
</template>

<style scoped>
.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.history-title {
  margin: 0;
}
.history-search-bar {
  margin-bottom: 12px;
}
.search-input {
  width: 360px;
}
.stats-card {
  margin-bottom: 12px;
}
.filter-select {
  min-width: 240px;
}
.filter-datepicker {
  min-width: 220px;
}
.skeleton-short {
  width: 60%;
}
</style>