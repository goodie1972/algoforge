<script setup lang="ts">
import { h } from 'vue'
import { NTag, NDataTable, NEmpty, NText, NAlert } from 'naive-ui'
import { getStrategyColor, getStrategyTextColor } from '@/utils/strategyColors'

const props = defineProps<{
  items: any[]
  loading?: boolean
  error?: string
  maxHeight?: number
}>()

const exitReasonLabels: Record<string, string> = {
  'strategy_exit': '策略出场',
  'mt4_history': 'MT4历史',
  'stop_loss': '止损',
  'take_profit': '止盈',
}

const columns = [
  { title: 'Ticket', key: 'ticket', width: 80 },
  {
    title: '策略', key: 'strategy', width: 160,
    render(row: any) {
      const name = row.strategy || row.comment || ''
      const color = getStrategyColor(name)
      const txtColor = getStrategyTextColor(name)
      return h(NTag, { color: { color, textColor: txtColor }, size: 'small', style: 'font-weight: 600;' },
        { default: () => name || '-' }
      )
    }
  },
  {
    title: '方向', key: 'order_type', width: 40,
    render(row: any) {
      const isBuy = row.order_type?.includes('BUY')
      return h(NTag, { type: isBuy ? 'success' : 'error', size: 'tiny' },
        { default: () => isBuy ? '多' : '空' }
      )
    }
  },
  { title: '手数', key: 'volume', width: 40 },
  { title: '开仓价', key: 'entry_price', width: 70,
    render(row: any) { return row.entry_price?.toFixed(2) }
  },
  { title: '平仓价', key: 'exit_price', width: 70,
    render(row: any) { return row.exit_price?.toFixed(2) }
  },
  {
    title: '盈亏', key: 'pnl', width: 70,
    render(row: any) {
      const val = row.pnl ?? 0
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  {
    title: '净盈亏', key: 'net_pnl', width: 70,
    render(row: any) {
      const val = (row.pnl ?? 0) + (row.swap ?? 0) + (row.commission ?? 0)
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  { title: '持仓', key: 'hold_seconds', width: 50,
    render(row: any) {
      const sec = row.hold_seconds ?? 0
      if (sec < 60) return `${sec}s`
      if (sec < 3600) return `${Math.round(sec / 60)}m`
      return `${(sec / 3600).toFixed(1)}h`
    }
  },
  {
    title: '出场原因', key: 'exit_reason', width: 70,
    render(row: any) {
      const reason = row.exit_reason || ''
      const label = exitReasonLabels[reason] || reason || '-'
      const type = reason === 'stop_loss' ? 'error' : reason === 'take_profit' ? 'success' : 'default'
      return h(NTag, { size: 'small', type }, { default: () => label })
    }
  },
  { title: '开仓时间', key: 'open_time', width: 125,
    render(row: any) {
      if (!row.open_time) return '-'
      if (typeof row.open_time === 'string') return row.open_time
      const ts = typeof row.open_time === 'number' ? row.open_time : parseInt(row.open_time)
      if (isNaN(ts)) return row.open_time
      return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
    }
  },
  { title: '平仓时间', key: 'close_time', width: 130 },
]
</script>

<template>
  <n-data-table v-if="loading" :columns="columns" :data="[]" :loading="true" :bordered="true" :max-height="maxHeight || 240" />
  <n-empty v-else-if="items.length === 0" :description="$t('trades.empty')">
    <template #extra><n-text depth="3">{{ $t('trades.empty_desc') }}</n-text></template>
  </n-empty>
  <n-alert v-else-if="error" type="error" :title="error" closable />
  <n-data-table v-else :columns="columns" :data="items" :bordered="true"
                :max-height="maxHeight || 240" striped :single-line="false" />
</template>
