<script setup lang="ts">
import { computed } from 'vue'
import type { BacktestResult } from '@/types'

const props = defineProps<{ result: BacktestResult }>()

const profitColor = computed(() => props.result.total_return >= 0 ? '#0ecb81' : '#f6465d')

const tradeColumns = [
  { title: '策略', key: 'strategy', width: 100 },
  { title: '方向', key: 'direction', width: 60,
    render(row: any) { return row.direction === 'BUY' ? '多' : '空' }
  },
  { title: '入场价', key: 'entry_price', width: 90 },
  { title: '出场价', key: 'exit_price', width: 90 },
  {
    title: '盈亏', key: 'pnl', width: 90,
    render(row: any) {
      const v = row.pnl ?? 0
      return { children: `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`, style: { color: v >= 0 ? '#0ecb81' : '#f6465d' } }
    }
  },
]

const strategyColumns = [
  { title: '策略', key: 'name', width: 120 },
  { title: '总盈亏', key: 'total_pnl', width: 100,
    render(row: any) {
      return { children: `${row.total_pnl >= 0 ? '+' : ''}$${row.total_pnl.toFixed(2)}`, style: { color: row.total_pnl >= 0 ? '#0ecb81' : '#f6465d' } }
    }
  },
  { title: '收益率', key: 'total_return_pct', width: 80,
    render(row: any) { return `${row.total_return_pct.toFixed(2)}%` }
  },
  { title: '交易次数', key: 'total_trades', width: 80 },
  { title: '最大回撤', key: 'max_drawdown', width: 80,
    render(row: any) { return `${row.max_drawdown.toFixed(2)}%` }
  },
]

const strategyData = computed(() => {
  const by = props.result.by_strategy || {}
  return Object.entries(by).map(([name, r]) => ({
    name,
    ...r,
  }))
})
</script>

<template>
  <n-space vertical size="medium">
    <!-- 汇总指标 -->
    <n-card title="回测结果" size="small">
      <n-grid :cols="5" :x-gap="16" :y-gap="12">
        <n-gi><n-statistic label="总盈亏" tabular-nums>
          <span :style="{ color: profitColor, fontWeight: 700 }">
            {{ result.total_return >= 0 ? '+' : '' }}${{ result.total_return.toFixed(2) }}
          </span>
        </n-statistic></n-gi>
        <n-gi><n-statistic label="总交易次数" tabular-nums>
          {{ result.total_trades }}
        </n-statistic></n-gi>
        <n-gi><n-statistic label="胜率" tabular-nums>
          {{ result.win_rate.toFixed(1) }}%
        </n-statistic></n-gi>
        <n-gi><n-statistic label="最大回撤" tabular-nums>
          {{ result.max_drawdown.toFixed(2) }}%
        </n-statistic></n-gi>
        <n-gi><n-statistic label="夏普比率" tabular-nums>
          {{ result.sharpe_ratio.toFixed(2) }}
        </n-statistic></n-gi>
      </n-grid>
    </n-card>

    <!-- 分策略 -->
    <n-card v-if="strategyData.length > 1" title="分策略对比" size="small">
      <n-data-table :columns="strategyColumns" :data="strategyData" :bordered="true" size="small" />
    </n-card>

    <!-- 交易记录 -->
    <n-card title="交易记录" size="small">
      <n-data-table :columns="tradeColumns" :data="result.trades"
                    :bordered="true" :max-height="400" size="small"
                    :pagination="{ pageSize: 20 }" />
    </n-card>
  </n-space>
</template>
