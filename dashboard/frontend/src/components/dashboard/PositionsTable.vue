<script setup lang="ts">
import { h, ref, watch } from 'vue'
import { usePositionStore } from '@/stores/positions'
import { NButton, NTag, NSpace, NDataTable, useDialog, useMessage } from 'naive-ui'
import { closePosition } from '@/api/client'
import { getStrategyColor, textColorForBg } from '@/utils/strategyColors'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const store = usePositionStore()
const dialog = useDialog()
const message = useMessage()
const loadingClose = ref<number | null>(null)

const totalPnLFlash = ref(false)
let _pLast = store.totalProfit, _pTimer: any = null
watch(() => store.totalProfit, (n: number) => {
  if (Math.abs(n - _pLast) < 0.01) return
  _pLast = n; totalPnLFlash.value = true
  if (_pTimer) clearTimeout(_pTimer)
  _pTimer = setTimeout(() => { totalPnLFlash.value = false }, 600)
})

const columns = [
  { title: 'Ticket', key: 'ticket', width: 100 },
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
    title: t('positions.direction'), key: 'order_type', width: 80,
    render(row: any) {
      const isBuy = row.order_type?.includes('BUY')
      return h(NTag, { type: isBuy ? 'success' : 'error', size: 'small' },
        { default: () => isBuy ? t('positions.buy') : t('positions.sell') }
      )
    }
  },
  {
    title: t('positions.strategy'), key: 'strategy', width: 180,
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
      // 策略名可能带 _BUY/_SELL 后缀，先尽量匹配
      const cleanName = name.replace(/_(BUY|SELL)$/, '')
      const color = colors[name] || colors[cleanName] || getStrategyColor(cleanName) || '#808080'
      const txtColor = textColorForBg(color)
      return h(NTag, { color: { color, textColor: txtColor }, size: 'small', style: 'font-weight: 600;' },
        { default: () => label }
      )
    }
  },
  { title: t('positions.volume'), key: 'volume', width: 70 },
  { title: t('positions.open_price'), key: 'open_price', width: 100,
    render(row: any) { return row.open_price?.toFixed(2) }
  },
  { title: t('positions.current_price'), key: 'current_price', width: 100,
    render(row: any) { return row.current_price?.toFixed(2) }
  },
  { title: t('positions.stop_loss'), key: 'stop_loss', width: 90,
    render(row: any) { return row.stop_loss || '-' }
  },
  { title: t('positions.take_profit'), key: 'take_profit', width: 90,
    render(row: any) { return row.take_profit || '-' }
  },
  {
    title: t('positions.profit'), key: 'profit', width: 100,
    render(row: any) {
      const val = row.profit ?? 0
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 600 } },
        `${val >= 0 ? '+' : ''}${val.toFixed(2)}`
      )
    }
  },
  {
    title: t('positions.actions'), key: 'actions', width: 140,
    render(row: any) {
      return h(NSpace, { size: 'small' }, {
        default: () => [
          h(NButton, {
            size: 'tiny', type: 'error', secondary: true,
            loading: loadingClose.value === row.ticket,
            onClick: () => {
              dialog.warning({
                title: t('positions.confirm_close'),
                content: t('positions.confirm_close_msg', { ticket: row.ticket }),
                positiveText: t('common.confirm'),
                negativeText: t('common.cancel'),
                onPositiveClick: async () => {
                  loadingClose.value = row.ticket
                  try {
                    await closePosition(row.ticket)
                    message.success(t('positions.close_success', { ticket: row.ticket }))
                    await store.fetch()
                  } catch (e: any) {
                    message.error(e?.message || t('positions.close_failed'))
                  }
                  loadingClose.value = null
                }
              })
            }
          }, { default: () => t('positions.close') }),
        ]
      })
    }
  },
]

const summaryRows = () => {
  return {
    ticket: { title: t('positions.summary'), colSpan: 2 },
    volume: { value: store.items.reduce((s, p) => s + p.volume, 0).toFixed(2) },
    profit: {
      value: (() => {
        const total = store.totalProfit
        return h('span', { style: { color: total >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
          `${total >= 0 ? '+' : ''}${total.toFixed(2)}`
        )
      })(),
      colSpan: 2
    },
  }
}
</script>

<template>
  <n-card :title="$t('positions.current')" size="small">
    <template #header-extra>
      <n-space size="small">
        <n-tag :bordered="false" type="success" size="small">{{ $t('positions.long_tag') }} {{ store.longCount }}</n-tag>
        <n-tag :bordered="false" type="error" size="small">{{ $t('positions.short_tag') }} {{ store.shortCount }}</n-tag>
        <n-tag :bordered="false" :type="store.totalProfit >= 0 ? 'success' : 'error'" size="small"
          :class="{ 'flash-num': totalPnLFlash }">
          {{ $t('positions.summary') }} ${{ store.totalProfit.toFixed(2) }}
        </n-tag>
      </n-space>
    </template>

    <!-- 加载态 -->
    <n-data-table v-if="store.loading" :columns="columns" :data="[]" :loading="true" :bordered="false" :max-height="400" />
    <!-- 空态 -->
    <n-empty v-else-if="store.items.length === 0" :description="$t('positions.empty')" style="padding: 40px 0;" />
    <!-- 错误态 -->
    <n-alert v-else-if="store.error" type="error" :title="store.error" closable style="margin-bottom:12px;" />
    <!-- 数据态 -->
    <n-data-table v-else :columns="columns" :data="store.items" :bordered="false"
                  :max-height="400" :summary="summaryRows" striped />
  </n-card>
</template>
