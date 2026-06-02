<script setup lang="ts">
import { onMounted } from 'vue'
import { useBacktestStore } from '@/stores/backtest'
import { useMessage } from 'naive-ui'

const backtest = useBacktestStore()
const message = useMessage()

onMounted(() => backtest.fetchHistory())

const columns = [
  { title: 'Job ID', key: 'job_id', width: 100 },
  {
    title: '状态', key: 'status', width: 90,
    render(row: any) {
      const labels: Record<string, string> = { completed: '已完成', running: '运行中', queued: '排队中', failed: '失败' }
      const types: Record<string, string> = { completed: 'success', running: 'info', queued: 'warning', failed: 'error' }
      return { children: labels[row.status] || row.status, type: types[row.status] || 'default' }
    }
  },
  { title: '创建时间', key: 'created_at', width: 170,
    render(row: any) { return row.created_at ? row.created_at.substring(0, 19) : '-' }
  },
  { title: '策略', key: 'strategies', width: 180,
    render(row: any) { return (row.params?.strategies || []).join(', ') || '-' }
  },
  { title: '周期', key: 'timeframe', width: 70,
    render(row: any) { return row.params?.timeframe || '-' }
  },
  { title: '日期范围', key: 'date_range', width: 200,
    render(row: any) { return `${row.params?.start_date || ''} ~ ${row.params?.end_date || ''}` }
  },
  {
    title: '结果', key: 'result', width: 200,
    render(row: any) {
      const r = row.result_summary
      if (!r) return '-'
      const pnl = r.total_return || 0
      return {
        children: `盈亏: ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)} | 胜率: ${r.win_rate || 0}% | 交易: ${r.total_trades || 0}次`,
        style: { fontSize: '12px' }
      }
    }
  },
]

async function refresh() {
  try {
    await backtest.fetchHistory()
    message.success('已刷新')
  } catch { /* ignore */ }
}
</script>

<template>
  <n-space vertical size="medium">
    <n-space align="center" justify="space-between">
      <n-text depth="3">历史回测记录</n-text>
      <n-button size="small" @click="refresh" :loading="false">刷新</n-button>
    </n-space>

    <n-empty v-if="backtest.history.length === 0" description="暂无回测记录" style="padding: 60px 0;">
      <template #extra>
        <n-text depth="3">在"回测"标签页提交回测任务</n-text>
      </template>
    </n-empty>

    <n-data-table v-else :columns="columns" :data="backtest.history"
                  :bordered="true" :max-height="500" size="small"
                  :pagination="{ pageSize: 15 }" striped />
  </n-space>
</template>
