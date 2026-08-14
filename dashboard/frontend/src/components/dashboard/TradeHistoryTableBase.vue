<script setup lang="ts">
import { h } from 'vue'
import { NTag, NDataTable, NEmpty, NText, NAlert } from 'naive-ui'
import { getStrategyColor, getStrategyTextColor } from '@/utils/strategyColors'
import { useI18n } from 'vue-i18n'
import { fmtRowTime } from '@/utils/timeFormat'

const { t } = useI18n()

const props = defineProps<{
  items: any[]
  loading?: boolean
  error?: string
  maxHeight?: number
}>()

const exitReasonLabels: Record<string, string> = {
  'strategy_exit': t('positions.exit_reason_strategy'),
  'mt4_history': t('positions.exit_reason_mt4'),
  'stop_loss': t('positions.exit_reason_sl'),
  'take_profit': t('positions.exit_reason_tp'),
}

const columns = [
  { title: 'Ticket', key: 'ticket', width: 80 },
  {
    title: t('positions.strategy'), key: 'strategy', width: 160,
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
    title: 'TF', key: 'timeframe', width: 50,
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
  {
    title: t('positions.direction'), key: 'order_type', width: 40,
    render(row: any) {
      const isBuy = row.order_type?.includes('BUY')
      return h(NTag, { type: isBuy ? 'success' : 'error', size: 'tiny' },
        { default: () => isBuy ? t('positions.buy') : t('positions.sell') }
      )
    }
  },
  { title: t('positions.volume'), key: 'volume', width: 40 },
  { title: t('positions.entry_price'), key: 'entry_price', width: 70,
    render(row: any) { return row.entry_price?.toFixed(2) }
  },
  { title: t('positions.exit_price'), key: 'exit_price', width: 70,
    render(row: any) { return row.exit_price?.toFixed(2) }
  },
  {
    title: t('positions.pnl'), key: 'pnl', width: 70,
    render(row: any) {
      const val = row.pnl ?? 0
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  {
    title: t('positions.net_pnl'), key: 'net_pnl', width: 70,
    render(row: any) {
      // 净盈亏 = 盈亏 - 手续费 - 过夜费（用绝对值，兼容正负存储）
      const val = (row.pnl ?? 0) - Math.abs(row.swap ?? 0) - Math.abs(row.commission ?? 0)
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  { title: t('positions.hold_time'), key: 'hold_seconds', width: 50,
    render(row: any) {
      const sec = row.hold_seconds ?? 0
      if (sec < 60) return `${sec}s`
      if (sec < 3600) return `${Math.round(sec / 60)}m`
      return `${(sec / 3600).toFixed(1)}h`
    }
  },
  {
    title: t('positions.exit_reason'), key: 'exit_reason', width: 70,
    render(row: any) {
      const reason = row.exit_reason || ''
      const label = exitReasonLabels[reason] || reason || '-'
      const type = reason === 'stop_loss' ? 'error' : reason === 'take_profit' ? 'success' : 'default'
      return h(NTag, { size: 'small', type }, { default: () => label })
    }
  },
  { title: t('positions.entry_time'), key: 'open_time', width: 125,
    render(row: any) {
      return fmtRowTime(row, 'open_time_ts', 'open_time')
    }
  },
  { title: t('positions.exit_time'), key: 'close_time', width: 130,
    render(row: any) {
      return fmtRowTime(row, 'close_time_ts', 'close_time')
    }
  },
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
