<script setup lang="ts">
import { h, ref, onMounted } from 'vue'
import { NTag } from 'naive-ui'
import { usePositionStore } from '@/stores/positions'
import { usePriceStore } from '@/stores/prices'
import TradingTerminal from '@/components/dashboard/TradingTerminal.vue'
import StrategySignals from '@/components/dashboard/StrategySignals.vue'

const positionStore = usePositionStore()
const priceStore = usePriceStore()

const expandedRowKeys = ref<(string | number)[]>([])

function renderPosExpand(row: any) {
  return h('div', { style: 'padding: 8px 16px; font-size: 12px; line-height: 1.8; display: grid; grid-template-columns: 1fr 1fr; gap: 12px;' }, [
    h('div', {}, [
      h('div', { style: 'font-weight: 700; color: #0ecb81;' }, '开仓信息'),
      h('div', {}, `Magic: ${row.magic || '-'}`),
      row.stop_loss ? h('div', {}, `止损距离: ${(Math.abs(row.open_price - row.stop_loss)).toFixed(2)}`) : null,
      row.take_profit ? h('div', {}, `止盈距离: ${(Math.abs(row.take_profit - row.open_price)).toFixed(2)}`) : null,
    ]),
    h('div', {}, [
      h('div', { style: 'font-weight: 700; color: #f0a020' }, '当前状态'),
      h('div', {}, `入场: ${row.open_price?.toFixed(2)} / 现价: ${row.current_price?.toFixed(2)}`),
      h('div', { style: { color: row.profit >= 0 ? '#0ecb81' : '#f6465d' } },
        `浮动盈亏: ${row.profit >= 0 ? '+' : ''}$${row.profit?.toFixed(2)}`),
    ]),
  ])
}

onMounted(() => {
  positionStore.fetch()
  priceStore.fetchPrice()
})

</script>

<template>
  <n-space vertical size="large">
    <!-- 图表 + 信号 -->
    <n-grid :cols="3" :x-gap="16">
      <n-gi :span="2"><TradingTerminal /></n-gi>
      <n-gi><StrategySignals /></n-gi>
    </n-grid>

    <!-- 持仓摘要 -->
    <n-card size="small" :bordered="true" title="当前持仓">
      <template v-if="positionStore.loading">
        <n-skeleton text :repeat="2" />
      </template>
      <template v-else-if="positionStore.items.length === 0">
        <n-empty description="暂无持仓">
          <template #extra>
            <n-text depth="3">引擎运行后自动加载持仓数据</n-text>
          </template>
        </n-empty>
      </template>
      <template v-else>
        <n-data-table
          :columns="[
            { type: 'expand', width: 35, renderExpand: renderPosExpand },
            { title: 'Ticket', key: 'ticket', width: 90 },
            { title: '方向', key: 'order_type', width: 70,
              render(row: any) {
                const isBuy = row.order_type?.includes('BUY')
                return h(NTag, { type: isBuy ? 'success' : 'error', size: 'small' },
                  { default: () => isBuy ? '多' : '空' }
                )
              }
            },
            {
              title: '策略', key: 'strategy', width: 110,
              render(row: any) {
                const name = row.comment || row._strategy_name || ''
                const magic = row.magic || ''
                const label = name || (magic ? `Magic ${magic}` : '-')
                const colors: Record<string, string> = {
                  'H1_v6_hybrid': '#2080f0',
                  'M30_rsi_bb': '#f0a020',
                  'sanqing_h1': '#9220f0',
                  'gold_auto_research': '#20c080',
                  'bakome_backup': '#808080',
                  'xaubot_backup': '#808080',
                }
                const color = colors[name] || '#808080'
                return h(NTag, { color: { color, textColor: '#fff' }, size: 'small' },
                  { default: () => label }
                )
              }
            },
            { title: '手数', key: 'volume', width: 60 },
            { title: '开仓价', key: 'open_price', width: 100,
              render(row: any) { return row.open_price?.toFixed(2) }
            },
            { title: '现价', key: 'current_price', width: 100,
              render(row: any) { return row.current_price?.toFixed(2) }
            },
            { title: '止损', key: 'stop_loss', width: 90,
              render(row: any) { return row.stop_loss || '-' }
            },
            { title: '止盈', key: 'take_profit', width: 90,
              render(row: any) { return row.take_profit || '-' }
            },
            { title: '开仓时间', key: 'open_time', width: 150,
              render(row: any) {
                if (!row.open_time) return '-'
                const ts = typeof row.open_time === 'number' ? row.open_time : parseInt(row.open_time)
                if (isNaN(ts)) return row.open_time
                return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
              }
            },
            { title: '盈亏', key: 'profit', width: 100,
              render(row: any) {
                const val = row.profit ?? 0
                return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
                  `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
                )
              }
            },
          ]"
          :data="positionStore.items"
          :bordered="true"
          :max-height="300"
          striped
          :single-line="false"
          size="small"
          v-model:expanded-row-keys="expandedRowKeys"
          :row-key="(row: any) => row.ticket"
        />
      </template>
    </n-card>
  </n-space>
</template>
