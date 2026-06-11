<script setup lang="ts">
import { h, ref, computed, onMounted, watch, reactive } from 'vue'
import { useTradeStore } from '@/stores/trades'
import { getTradeStats, getTradeAnalysis } from '@/api/client'
import type { TradeStats } from '@/types'
import { NTag, NButton, NDataTable, NEmpty, NSkeleton, NAlert, NSpace, NTabs, NTabPane, NGrid, NGi, NStatistic, NCard, NSelect, NDatePicker, NIcon, NSpin, NInput } from 'naive-ui'

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
    analysisCache[ticket] = { error: e?.message || '获取分析失败' }
  } finally {
    analysisLoading[ticket] = false
  }
}

function renderAnalysis(row: any) {
  const ticket = row.ticket
  if (analysisLoading[ticket]) {
    return h(NSpin, {}, { default: () => '加载分析中...' })
  }
  const data = analysisCache[ticket]
  if (!data) return h('span', '点击展开分析')
  if (data.error) return h('span', { style: { color: '#f6465d' } }, `分析失败: ${data.error}`)

  const sec = (s: number) => s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s/60)}m` : `${(s/3600).toFixed(1)}h`

  return h('div', { style: 'padding: 12px 24px; font-size: 13px; line-height: 1.6;' }, [
    h('div', { style: 'display: grid; grid-template-columns: 1fr 1fr; gap: 16px;' }, [
      // 左列：开仓分析
      h('div', {}, [
        h('div', { style: 'font-weight: 700; margin-bottom: 8px; color: #0ecb81;' }, '开仓逻辑'),
        h('div', {}, `系统: ${data.entry_analysis?.system || '未知'}`),
        data.entry_analysis?.likely_conditions?.length
          ? h('div', { style: 'margin-top: 4px;' }, [
              h('span', { style: 'color: #888;' }, '触发条件: '),
              ...data.entry_analysis.likely_conditions.map((c: string, i: number) =>
                h('span', { style: 'background: #1a1a2e; padding: 1px 6px; border-radius: 3px; margin-right: 4px;' }, c)
              ),
            ])
          : null,
        data.entry_analysis?.factors
          ? h('div', { style: 'margin-top: 8px;' }, [
              h('div', { style: 'color: #888; margin-bottom: 4px;' }, '评分因子:'),
              ...data.entry_analysis.factors.map((f: any) =>
                h('div', { style: 'font-size: 12px; padding: 2px 0;' }, `• ${f.name}: ${f.desc}`)
              ),
            ])
          : null,
      ]),
      // 右列：平仓分析
      h('div', {}, [
        h('div', { style: 'font-weight: 700; margin-bottom: 8px; color: #f6465d;' }, '平仓逻辑'),
        h('div', {}, `方式: ${data.exit_analysis?.label || '未知'}`),
        h('div', { style: 'margin-top: 4px;' }, `逻辑: ${data.exit_analysis?.logic || '无'}`),
        data.exit_analysis?.is_loss
          ? h('div', { style: 'margin-top: 12px;' }, [
              h('div', { style: 'font-weight: 700; color: #f0a020; margin-bottom: 6px;' }, '亏损分析 & 优化建议'),
              ...(data.exit_analysis?.loss_analysis?.possible_reasons || []).map((r: string) =>
                h('div', { style: 'font-size: 12px; padding: 2px 0;' }, `• ${r}`)
              ),
              ...(data.exit_analysis?.loss_analysis?.suggestions || []).map((s: string) =>
                h('div', { style: 'font-size: 12px; padding: 2px 0; color: #7cb8ff;' }, `→ ${s.replace(/\\n/g, ' ')}`)
              ),
            ])
          : h('div', { style: 'margin-top: 8px; color: #0ecb81;' }, '✅ 盈利单'),
      ]),
    ]),
  ])
}

const columns = [
  {
    type: 'expand' as const,
    width: 40,
    renderExpand: (row: any) => renderAnalysis(row),
  },
  { title: 'Ticket', key: 'ticket', width: 80, sortable: true, sorter: (a: any, b: any) => a.ticket - b.ticket },
  { title: '策略', key: 'strategy', width: 100, sortable: true,
    render(row: any) {
      return h(NTag, { size: 'small', type: row.strategy?.includes('stoch') ? 'info' : 'warning' },
        { default: () => row.strategy }
      )
    }
  },
  {
    title: '方向', key: 'order_type', width: 70, sortable: true,
    render(row: any) {
      const isBuy = row.order_type?.includes('BUY')
      return h(NTag, { type: isBuy ? 'success' : 'error', size: 'small' },
        { default: () => isBuy ? '多头' : '空头' }
      )
    }
  },
  { title: '手数', key: 'volume', width: 60, sortable: true },
  { title: '开仓价', key: 'entry_price', width: 100, sortable: true,
    render(row: any) { return row.entry_price?.toFixed(2) }
  },
  { title: '平仓价', key: 'exit_price', width: 100, sortable: true,
    render(row: any) { return row.exit_price?.toFixed(2) }
  },
  {
    title: '盈亏', key: 'pnl', width: 100, sortable: true,
    render(row: any) {
      const val = row.pnl ?? 0
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  {
    title: '盈亏+佣金', key: 'net_pnl', width: 100,
    render(row: any) {
      const val = (row.pnl ?? 0) + (row.swap ?? 0) + (row.commission ?? 0)
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  { title: '持仓时长', key: 'hold_seconds', width: 90,
    render(row: any) {
      const sec = row.hold_seconds ?? 0
      if (sec < 60) return `${sec}s`
      if (sec < 3600) return `${Math.round(sec / 60)}m`
      return `${(sec / 3600).toFixed(1)}h`
    }
  },
  { title: '出场原因', key: 'exit_reason', width: 100,
    render(row: any) {
      const reason = row.exit_reason || '-'
      return h(NTag, { size: 'small', type: 'default' }, { default: () => reason })
    }
  },
  { title: '开仓时间', key: 'open_time', width: 150 },
  { title: '平仓时间', key: 'close_time', width: 150 },
]

// ── 策略统计标签页 ──────────────────────────────────────

const statsData = ref<TradeStats | null>(null)
const statsLoading = ref(false)
const statsError = ref<string | null>(null)

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
  } catch (e: any) {
    statsError.value = e?.message || '获取统计失败'
  } finally {
    statsLoading.value = false
  }
}

watch(activeTab, (tab) => {
  if (tab === 'stats' && !statsData.value) loadStats()
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
    { label: '总净盈亏', value: s.total_net_profit, fmt: (v: number) => `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`, color: s.total_net_profit >= 0 ? '#0ecb81' : '#f6465d' },
    { label: 'Profit Factor', value: s.profit_factor, fmt: (v: any) => v, color: undefined },
    { label: '总交易次数', value: s.total_trades, fmt: (v: number) => v.toString(), color: undefined },
    { label: '胜率', value: s.win_rate, fmt: (v: number) => `${v}%`, color: s.win_rate >= 50 ? '#0ecb81' : '#f6465d' },
    { label: 'Expected Payoff', value: s.expected_payoff, fmt: (v: number) => `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`, color: s.expected_payoff >= 0 ? '#0ecb81' : '#f6465d' },
    { label: '最大连亏', value: s.max_consecutive_losses, fmt: (v: number) => `${v} 次`, color: undefined },
  ]
})

// 分策略透视表
const statsTableData = computed(() => {
  const by = statsData.value?.by_magic || {}
  return Object.entries(by).map(([magic, s]: [string, any]) => ({
    magic,
    ...s,
  }))
})

const statsColumns = [
  { title: 'Magic', key: 'magic', width: 80, fixed: 'left' as const },
  {
    title: '策略', key: 'strategy', width: 130,
    render(row: any) {
      return h(NTag, { size: 'small', type: row.strategy?.includes('stoch') ? 'info' : 'warning' },
        { default: () => row.strategy }
      )
    }
  },
  { title: '总盈亏', key: 'total_net_profit', width: 100, sortable: true,
    render(row: any) {
      const v = row.total_net_profit ?? 0
      return h('span', { style: { color: v >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`
      )
    }
  },
  { title: '毛利', key: 'gross_profit', width: 90,
    render(row: any) { return h('span', { style: { color: '#0ecb81' } }, `$${row.gross_profit?.toFixed(2)}`) }
  },
  { title: '毛损', key: 'gross_loss', width: 90,
    render(row: any) { return h('span', { style: { color: '#f6465d' } }, `$${row.gross_loss?.toFixed(2)}`) }
  },
  { title: 'PF', key: 'profit_factor', width: 70,
    render(row: any) { return row.profit_factor }
  },
  { title: '总交易', key: 'total_trades', width: 70, sortable: true },
  {
    title: '多(胜率)', key: 'long_won_pct', width: 90,
    render(row: any) { return `${row.long_trades} (${row.long_won_pct}%)` }
  },
  {
    title: '空(胜率)', key: 'short_won_pct', width: 90,
    render(row: any) { return `${row.short_trades} (${row.short_won_pct}%)` }
  },
  { title: '总胜率', key: 'win_rate', width: 70,
    render(row: any) { return `${row.win_rate}%` }
  },
  {
    title: '平均盈利', key: 'avg_profit_trade', width: 90,
    render(row: any) { return `$${row.avg_profit_trade?.toFixed(2)}` }
  },
  {
    title: '平均亏损', key: 'avg_loss_trade', width: 90,
    render(row: any) { return `$${row.avg_loss_trade?.toFixed(2)}` }
  },
  { title: '盈利/亏损比', key: 'ratio_avg_profit_loss', width: 90 },
  {
    title: '最大盈利', key: 'largest_profit_trade', width: 90,
    render(row: any) { return `$${row.largest_profit_trade?.toFixed(2)}` }
  },
  {
    title: '最大亏损', key: 'largest_loss_trade', width: 90,
    render(row: any) { return `$${row.largest_loss_trade?.toFixed(2)}` }
  },
  { title: '平均持仓', key: 'avg_hold_seconds', width: 80,
    render(row: any) {
      const sec = row.avg_hold_seconds ?? 0
      if (sec < 60) return `${sec}s`
      if (sec < 3600) return `${Math.round(sec / 60)}m`
      return `${(sec / 3600).toFixed(1)}h`
    }
  },
  { title: '连盈(次)', key: 'max_consecutive_wins', width: 80 },
  { title: '连亏(次)', key: 'max_consecutive_losses', width: 80 },
  { title: '连盈($)', key: 'max_consecutive_wins_pnl', width: 80,
    render(row: any) { return `$${row.max_consecutive_wins_pnl?.toFixed(2)}` }
  },
  { title: '连亏($)', key: 'max_consecutive_losses_pnl', width: 80,
    render(row: any) { return `$${row.max_consecutive_losses_pnl?.toFixed(2)}` }
  },
]
</script>

<template>
  <n-space vertical size="large">
    <div style="display: flex; justify-content: space-between; align-items: center;">
      <n-h2 style="margin:0;">历史成交</n-h2>
      <n-space size="small">
        <n-tag :bordered="false" type="info">共 {{ store.items.length }} 笔</n-tag>
        <n-button size="small" secondary :loading="refreshLoading" @click="refresh">
          刷新
        </n-button>
      </n-space>
    </div>

    <n-tabs v-model:value="activeTab" type="line" animated>
    <!-- ═══ 成交明细 ═══ -->
      <n-tab-pane name="history" tab="成交明细">
        <n-space style="margin-bottom: 12px;">
          <n-input v-model:value="searchQuery" placeholder="搜索: 策略名 / Magic / Ticket"
                   clearable style="width: 360px;">
            <template #prefix>
              <n-icon :component="SearchOutline" />
            </template>
          </n-input>
          <n-tag :bordered="false" type="info">共 {{ filteredData.length }} 笔</n-tag>
        </n-space>
        <n-data-table v-if="store.loading" :columns="columns" :data="[]" :loading="true" :bordered="true" :max-height="600" />
        <n-empty v-else-if="store.items.length === 0" description="暂无历史成交">
          <template #extra>
            <n-text depth="3">启动引擎后自动记录已平仓订单</n-text>
          </template>
        </n-empty>
        <n-alert v-else-if="store.error" type="error" :title="store.error" closable />
        <n-data-table v-else :columns="columns" :data="filteredData" :bordered="true"
                      :max-height="700" striped :single-line="false"
                      v-model:expanded-row-keys="expandedRowKeys"
                      :row-key="(row: any) => row.ticket" />
      </n-tab-pane>

      <!-- ═══ 策略统计 ═══ -->
      <n-tab-pane name="stats" tab="策略统计">
        <!-- 筛选栏 -->
        <n-card size="small" :bordered="true" style="margin-bottom: 12px;">
          <n-space align="center" size="medium">
            <n-select v-if="strategyOptions.length"
              v-model:value="selectedStrategies" :options="strategyOptions"
              multiple clearable placeholder="筛选策略" style="min-width: 240px;" />
            <n-date-picker v-model:value="dateRange" type="daterange" clearable
              placeholder="选择日期范围" style="min-width: 220px;" />
            <n-button type="primary" size="small" @click="loadStats" :loading="statsLoading">
              查询
            </n-button>
          </n-space>
        </n-card>

        <!-- 加载态 -->
        <template v-if="statsLoading">
          <n-card size="small">
            <n-space vertical size="medium">
              <n-skeleton text :repeat="3" />
              <n-skeleton text style="width: 60%;" />
            </n-space>
          </n-card>
        </template>

        <!-- 空态 -->
        <n-empty v-else-if="!statsData || statsData.summary.total_trades === 0" description="暂无已平仓记录">
          <template #extra>
            <n-text depth="3">引擎运行并产生平仓后自动统计</n-text>
          </template>
        </n-empty>

        <!-- 错误态 -->
        <n-alert v-else-if="statsError" type="error" :title="statsError" closable />

        <!-- 数据态 -->
        <template v-else>
          <!-- 汇总指标卡片 -->
          <n-card size="small" :bordered="true" style="margin-bottom: 12px;">
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
                          :scroll-x="1600" />
          </n-card>
        </template>
      </n-tab-pane>
    </n-tabs>
  </n-space>
</template>
