<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { useTradeStore } from '@/stores/trades'
import { NTag, NButton, NDataTable, NEmpty, NSkeleton, NAlert, NSpace } from 'naive-ui'

const store = useTradeStore()
const refreshLoading = ref(false)

onMounted(() => store.fetch())

async function refresh() {
  refreshLoading.value = true
  await store.fetch()
  refreshLoading.value = false
}

const columns = [
  { title: 'Ticket', key: 'ticket', width: 80 },
  { title: '策略', key: 'strategy', width: 100,
    render(row: any) {
      return h(NTag, { size: 'small', type: row.strategy?.includes('stoch') ? 'info' : 'warning' },
        { default: () => row.strategy }
      )
    }
  },
  {
    title: '方向', key: 'order_type', width: 70,
    render(row: any) {
      const isBuy = row.order_type?.includes('BUY')
      return h(NTag, { type: isBuy ? 'success' : 'error', size: 'small' },
        { default: () => isBuy ? '多头' : '空头' }
      )
    }
  },
  { title: '手数', key: 'volume', width: 60 },
  { title: '开仓价', key: 'entry_price', width: 100,
    render(row: any) { return row.entry_price?.toFixed(2) }
  },
  { title: '平仓价', key: 'exit_price', width: 100,
    render(row: any) { return row.exit_price?.toFixed(2) }
  },
  {
    title: '盈亏', key: 'pnl', width: 100,
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

    <!-- 加载态 -->
    <n-data-table v-if="store.loading" :columns="columns" :data="[]" :loading="true" :bordered="true" :max-height="600" />
    <!-- 空态 -->
    <n-empty v-else-if="store.items.length === 0" description="暂无历史成交">
      <template #extra>
        <n-text depth="3">启动引擎后自动记录已平仓订单</n-text>
      </template>
    </n-empty>
    <!-- 错误态 -->
    <n-alert v-else-if="store.error" type="error" :title="store.error" closable />
    <!-- 数据态 -->
    <n-data-table v-else :columns="columns" :data="store.items" :bordered="true"
                  :max-height="700" striped :single-line="false" />
  </n-space>
</template>
