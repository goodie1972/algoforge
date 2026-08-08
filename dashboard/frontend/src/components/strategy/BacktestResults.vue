<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useBacktestStore } from '@/stores/backtest'
import { useMessage } from 'naive-ui'

const { t } = useI18n()
const backtest = useBacktestStore()
const message = useMessage()

onMounted(() => backtest.fetchHistory())

const columns = [
  { title: 'Job ID', key: 'job_id', width: 100 },
  {
    title: t('backtest.status'), key: 'status', width: 90,
    render(row: any) {
      const labels: Record<string, string> = { completed: t('backtest.completed'), running: t('backtest.running'), queued: t('backtest.queued'), failed: t('backtest.failed') }
      const types: Record<string, string> = { completed: 'success', running: 'info', queued: 'warning', failed: 'error' }
      return { children: labels[row.status] || row.status, type: types[row.status] || 'default' }
    }
  },
  { title: t('backtest.created_at'), key: 'created_at', width: 170,
    render(row: any) { return row.created_at ? row.created_at.substring(0, 19) : '-' }
  },
  { title: t('backtest.strategy'), key: 'strategies', width: 180,
    render(row: any) { return (row.params?.strategies || []).join(', ') || '-' }
  },
  { title: t('backtest.timeframe'), key: 'timeframe', width: 70,
    render(row: any) { return row.params?.timeframe || '-' }
  },
  { title: t('backtest.date_range'), key: 'date_range', width: 200,
    render(row: any) { return `${row.params?.start_date || ''} ~ ${row.params?.end_date || ''}` }
  },
  {
    title: t('backtest.result'), key: 'result', width: 200,
    render(row: any) {
      const r = row.result_summary
      if (!r) return '-'
      const pnl = r.total_return || 0
      return {
        children: `${t('backtest.pnl')}: ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)} | ${t('backtest.win_rate')}: ${r.win_rate || 0}% | ${t('backtest.total_trades')}: ${r.total_trades || 0}${t('backtest.times')}`,
        style: { fontSize: '12px' }
      }
    }
  },
]

async function refresh() {
  try {
    await backtest.fetchHistory()
    message.success(t('backtest.refresh_success'))
  } catch { /* ignore */ }
}
</script>

<template>
  <n-space vertical size="medium">
    <n-space align="center" justify="space-between">
      <n-text depth="3">{{ $t('backtest.history') }}</n-text>
      <n-button size="small" @click="refresh" :loading="false">{{ $t('backtest.refresh') }}</n-button>
    </n-space>

    <n-empty v-if="backtest.history.length === 0" :description="$t('backtest.no_records')" style="padding: 60px 0;">
      <template #extra>
        <n-text depth="3">{{ $t('backtest.submit_in_tab') }}</n-text>
      </template>
    </n-empty>

    <n-data-table v-else :columns="columns" :data="backtest.history"
                  :bordered="true" :max-height="500" size="small"
                  :pagination="{ pageSize: 15 }" striped />
  </n-space>
</template>
