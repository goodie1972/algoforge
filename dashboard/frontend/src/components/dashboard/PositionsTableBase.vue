<script setup lang="ts">
import { h, ref, computed } from 'vue'
import { usePositionStore } from '@/stores/positions'
import { useMessage, useDialog, NButton, NTag, NSpace, NInputNumber, NDataTable, NEmpty, NText, NAlert, NDrawer, NDrawerContent, NFormItem } from 'naive-ui'
import { closePosition, modifyPosition } from '@/api/client'
import { getStrategyColor, textColorForBg } from '@/utils/strategyColors'
import { useI18n } from 'vue-i18n'
import { fmtRowTime } from '@/utils/timeFormat'

const { t } = useI18n()
const store = usePositionStore()
const message = useMessage()
const dialog = useDialog()

const editingTicket = ref<number | null>(null)
const editSl = ref(0)
const editTp = ref(0)
const loadingClose = ref<number | null>(null)
const loadingModify = ref(false)
const showDrawer = computed(() => editingTicket.value != null)
const expandedRowKeys = ref<(string | number)[]>([])

function renderPosExpand(row: any) {
  return h('div', { style: 'padding: 12px 24px; font-size: 13px; line-height: 1.8; display: grid; grid-template-columns: 1fr 1fr; gap: 16px;' }, [
    h('div', {}, [
      h('div', { style: 'font-weight: 700; margin-bottom: 8px; color: #0ecb81;' }, t('positions.open_info')),
      h('div', {}, t('positions.magic_label') + ': ' + (row.magic || '-')),
      h('div', {}, t('positions.strategy_label') + ': ' + (row.comment || row._strategy_name || '-')),
      h('div', {}, t('positions.open_time_label') + ': ' + fmtRowTime(row, 'open_time_ts', 'open_time')),
      row.stop_loss ? h('div', {}, t('positions.sl_distance') + ': ' + (Math.abs(row.open_price - row.stop_loss)).toFixed(2)) : null,
      row.take_profit ? h('div', {}, t('positions.tp_distance') + ': ' + (Math.abs(row.take_profit - row.open_price)).toFixed(2)) : null,
    ]),
    h('div', {}, [
      h('div', { style: 'font-weight: 700; margin-bottom: 8px; color: #f0a020;' }, t('positions.status')),
      h('div', {}, t('positions.entry_price_label') + ': ' + row.open_price?.toFixed(2)),
      h('div', {}, t('positions.current_price_label') + ': ' + row.current_price?.toFixed(2)),
      h('div', { style: { color: row.profit >= 0 ? '#0ecb81' : '#f6465d' } },
        t('positions.floating_pnl') + ': ' + (row.profit >= 0 ? '+' : '') + '$' + row.profit?.toFixed(2)),
      row.stop_loss ? h('div', {}, t('positions.sl_label') + ': ' + row.stop_loss.toFixed(2)) : null,
      row.take_profit ? h('div', {}, t('positions.tp_label') + ': ' + row.take_profit.toFixed(2)) : null,
    ]),
  ])
}

const columns = [
  { type: 'expand' as const, width: 30, renderExpand: renderPosExpand },
  { title: 'Ticket', key: 'ticket', width: 80 },
  {
    title: t('positions.strategy'), key: 'strategy', width: 150,
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
      return h(NTag, { type: isBuy ? 'success' : 'error', size: 'small' },
        { default: () => isBuy ? t('positions.buy') : t('positions.sell') }
      )
    }
  },
  { title: t('positions.volume'), key: 'volume', width: 40 },
  { title: t('positions.open_price'), key: 'open_price', width: 80,
    render(row: any) { return row.open_price?.toFixed(2) }
  },
  { title: t('positions.current_price'), key: 'current_price', width: 80,
    render(row: any) { return row.current_price?.toFixed(2) }
  },
  { title: t('positions.stop_loss'), key: 'stop_loss', width: 80,
    render(row: any) { return row.stop_loss || '-' }
  },
  { title: t('positions.take_profit'), key: 'take_profit', width: 80,
    render(row: any) { return row.take_profit || '-' }
  },
  { title: t('positions.open_time'), key: 'open_time', width: 120,
    render(row: any) {
      return fmtRowTime(row, 'open_time_ts', 'open_time')
    }
  },
  {
    title: t('positions.profit'), key: 'profit', width: 80,
    render(row: any) {
      const val = row.profit ?? 0
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  {
    title: t('positions.actions'), key: 'actions', width: 135,
    render(row: any) {
      return h(NSpace, { size: 'small' }, {
        default: () => [
          h(NButton, {
            size: 'tiny', secondary: true,
            onClick: () => {
              editingTicket.value = row.ticket
              editSl.value = row.stop_loss || 0
              editTp.value = row.take_profit || 0
            }
          }, { default: () => t('positions.modify_sltp_btn') }),
          h(NButton, {
            size: 'tiny', type: 'error', secondary: true,
            loading: loadingClose.value === row.ticket,
            onClick: () => {
              dialog.warning({
              title: t('positions.confirm_close'),
                content: t('positions.confirm_close_msg', { ticket: '#' + row.ticket, direction: row.order_type?.includes('BUY') ? t('positions.buy') : t('positions.sell'), volume: row.volume }),
                positiveText: t('positions.confirm_close'),
                negativeText: t('common.cancel'),
                onPositiveClick: async () => {
                  loadingClose.value = row.ticket
                  try {
                    await closePosition(row.ticket)
                    message.success(t('positions.close_success', { ticket: '#' + row.ticket }))
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

async function handleModify() {
  if (editingTicket.value == null) return
  loadingModify.value = true
  try {
    await modifyPosition(editingTicket.value, editSl.value, editTp.value)
    message.success(t('positions.modify_sl_tp_updated', { ticket: '#' + editingTicket.value }))
    editingTicket.value = null
    await store.fetch()
  } catch (e: any) {
    message.error(e?.message || t('positions.modify_failed'))
  }
  loadingModify.value = false
}
</script>

<template>
  <div>
    <!-- 加载态 -->
    <n-data-table v-if="store.loading" :columns="columns" :data="[]" :loading="true" :bordered="true" :max-height="600" />
    <!-- 空态 -->
    <n-empty v-else-if="store.items.length === 0" :description="$t('positions.empty')">
      <template #extra>
        <n-text depth="3">{{ $t('positions.empty_desc') }}</n-text>
      </template>
    </n-empty>
    <!-- 错误态 -->
    <n-alert v-else-if="store.error" type="error" :title="store.error" closable />
    <!-- 数据态 -->
    <n-data-table v-else :columns="columns" :data="store.items" :bordered="true"
                  :max-height="600" striped :single-line="false"
                  v-model:expanded-row-keys="expandedRowKeys"
                  :row-key="(row: any) => row.ticket" />

    <!-- 修改 SL/TP 抽屉 -->
    <n-drawer v-model:show="showDrawer" :width="360" placement="right">
      <n-drawer-content :title="`${$t('positions.modify_sltp')} - #${editingTicket}`" closable @close="editingTicket = null">
        <n-space vertical size="large">
          <n-form-item :label="$t('positions.sl')">
            <app-input-number v-model:value="editSl" :step="0.01" style="width:100%;" />
          </n-form-item>
          <n-form-item :label="$t('positions.tp')">
            <app-input-number v-model:value="editTp" :step="0.01" style="width:100%;" />
          </n-form-item>
          <n-button type="primary" :loading="loadingModify" @click="handleModify" block>
            {{ $t('positions.confirm_modify') }}
          </n-button>
        </n-space>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>
