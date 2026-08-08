<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { BacktestResult } from '@/types'

const { t } = useI18n()
const props = defineProps<{ result: BacktestResult }>()

const profitColor = computed(() => props.result.total_return >= 0 ? '#0ecb81' : '#f6465d')

const tradeColumns = [
  { title: t('backtest.strategy'), key: 'strategy', width: 100 },
  { title: t('backtest.direction'), key: 'direction', width: 60,
    render(row: any) { return row.direction === 'BUY' ? t('backtest.buy') : t('backtest.sell') }
  },
  { title: t('backtest.entry_price'), key: 'entry_price', width: 90 },
  { title: t('backtest.exit_price'), key: 'exit_price', width: 90 },
  {
    title: t('backtest.pnl'), key: 'pnl', width: 90,
    render(row: any) {
      const v = row.pnl ?? 0
      return { children: `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`, style: { color: v >= 0 ? '#0ecb81' : '#f6465d' } }
    }
  },
]

const strategyColumns = [
  { title: t('backtest.strategy'), key: 'name', width: 120 },
  { title: t('backtest.total_pnl'), key: 'total_pnl', width: 100,
    render(row: any) {
      return { children: `${row.total_pnl >= 0 ? '+' : ''}$${row.total_pnl.toFixed(2)}`, style: { color: row.total_pnl >= 0 ? '#0ecb81' : '#f6465d' } }
    }
  },
  { title: t('backtest.total_return_pct'), key: 'total_return_pct', width: 80,
    render(row: any) { return `${row.total_return_pct.toFixed(2)}%` }
  },
  { title: t('backtest.total_trades'), key: 'total_trades', width: 80 },
  { title: t('backtest.max_drawdown'), key: 'max_drawdown', width: 80,
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
    <n-card :title="$t('backtest.result')" size="small">
      <n-grid :cols="5" :x-gap="16" :y-gap="12">
        <n-gi><n-statistic :label="$t('backtest.total_pnl')" tabular-nums>
          <span :style="{ color: profitColor, fontWeight: 700 }">
            {{ result.total_return >= 0 ? '+' : '' }}${{ result.total_return.toFixed(2) }}
          </span>
        </n-statistic></n-gi>
        <n-gi><n-statistic :label="$t('backtest.total_trades')" tabular-nums>
          {{ result.total_trades }}
        </n-statistic></n-gi>
        <n-gi><n-statistic :label="$t('backtest.win_rate')" tabular-nums>
          {{ result.win_rate.toFixed(1) }}%
        </n-statistic></n-gi>
        <n-gi><n-statistic :label="$t('backtest.max_drawdown')" tabular-nums>
          {{ result.max_drawdown.toFixed(2) }}%
        </n-statistic></n-gi>
        <n-gi><n-statistic :label="$t('backtest.sharpe')" tabular-nums>
          {{ result.sharpe_ratio.toFixed(2) }}
        </n-statistic></n-gi>
      </n-grid>
    </n-card>

    <!-- 分策略 -->
    <n-card v-if="strategyData.length > 1" :title="$t('backtest.per_strategy')" size="small">
      <n-data-table :columns="strategyColumns" :data="strategyData" :bordered="true" size="small" />
    </n-card>

    <!-- 交易记录 -->
    <n-card :title="$t('backtest.records')" size="small">
      <n-data-table :columns="tradeColumns" :data="result.trades"
                    :bordered="true" :max-height="400" size="small"
                    :pagination="{ pageSize: 20 }" />
    </n-card>
  </n-space>
</template>
