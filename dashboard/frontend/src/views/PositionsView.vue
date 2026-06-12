<script setup lang="ts">
import { h, ref, computed, onMounted } from 'vue'
import { usePositionStore } from '@/stores/positions'
import { useAccountStore } from '@/stores/account'
import { useTradeStore } from '@/stores/trades'
import { useMessage, useDialog, NButton, NTag, NSpace, NInput, NDataTable, NCard, NEmpty, NText, NModal } from 'naive-ui'
import { closePosition, modifyPosition } from '@/api/client'
import AccountPanel from '@/components/dashboard/AccountPanel.vue'

const store = usePositionStore()
const account = useAccountStore()
const tradeStore = useTradeStore()
const message = useMessage()
const dialog = useDialog()
const editingTicket = ref<number | null>(null)
const editSl = ref(0)
const editTp = ref(0)
const loadingClose = ref<number | null>(null)
const loadingModify = ref(false)
const showDrawer = computed(() => editingTicket.value != null)
const showHistoryModal = ref(false)
const fullHistory = ref<any[]>([])
const loadingFullHistory = ref(false)

onMounted(() => tradeStore.fetch(10))

async function openFullHistory() {
  showHistoryModal.value = true
  loadingFullHistory.value = true
  try {
    const { getTradeHistory } = await import('@/api/client')
    fullHistory.value = await getTradeHistory(999)
  } catch { /* ignore */ }
  finally { loadingFullHistory.value = false }
}

const expandedRowKeys = ref<(string | number)[]>([])

function renderPositionExpand(row: any) {
  return h('div', { style: 'padding: 12px 24px; font-size: 13px; line-height: 1.8; display: grid; grid-template-columns: 1fr 1fr; gap: 16px;' }, [
    h('div', {}, [
      h('div', { style: 'font-weight: 700; margin-bottom: 8px; color: #0ecb81;' }, '开仓信息'),
      h('div', {}, `Magic: ${row.magic || '-'}`),
      h('div', {}, `策略名: ${row.comment || row._strategy_name || '-'}`),
      h('div', {}, `开仓时间: ${row.open_time ? new Date(row.open_time * 1000).toLocaleString() : '-'}`),
      row.stop_loss ? h('div', {}, `止损距离: ${(Math.abs(row.open_price - row.stop_loss)).toFixed(2)}`) : null,
      row.take_profit ? h('div', {}, `止盈距离: ${(Math.abs(row.take_profit - row.open_price)).toFixed(2)}`) : null,
    ]),
    h('div', {}, [
      h('div', { style: 'font-weight: 700; margin-bottom: 8px; color: #f0a020;' }, '当前状态'),
      h('div', {}, `入场价: ${row.open_price?.toFixed(2)}`),
      h('div', {}, `现价: ${row.current_price?.toFixed(2)}`),
      h('div', { style: { color: row.profit >= 0 ? '#0ecb81' : '#f6465d' } },
        `浮动盈亏: ${row.profit >= 0 ? '+' : ''}$${row.profit?.toFixed(2)}`),
      row.stop_loss ? h('div', {}, `止损位: ${row.stop_loss.toFixed(2)}`) : null,
      row.take_profit ? h('div', {}, `止盈位: ${row.take_profit.toFixed(2)}`) : null,
    ]),
  ])
}

const columns = [
  {
    type: 'expand' as const,
    width: 40,
    renderExpand: renderPositionExpand,
  },
  { title: 'Ticket', key: 'ticket', width: 90 },
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
  {
    title: '方向', key: 'order_type', width: 70,
    render(row: any) {
      const isBuy = row.order_type?.includes('BUY')
      return h(NTag, { type: isBuy ? 'success' : 'error', size: 'small' },
        { default: () => isBuy ? '📈 多' : '📉 空' }
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
  {
    title: '盈亏', key: 'profit', width: 100,
    render(row: any) {
      const val = row.profit ?? 0
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  {
    title: '操作', key: 'actions', width: 120,
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
          }, { default: () => '改 SL/TP' }),
          h(NButton, {
            size: 'tiny', type: 'error', secondary: true,
            loading: loadingClose.value === row.ticket,
            onClick: () => {
              dialog.warning({
                title: '确认平仓',
                content: `确定平掉 #${row.ticket} (${row.order_type?.includes('BUY') ? '多' : '空'} ${row.volume}手) 吗？`,
                positiveText: '确认平仓',
                negativeText: '取消',
                onPositiveClick: async () => {
                  loadingClose.value = row.ticket
                  try {
                    await closePosition(row.ticket)
                    message.success(`#${row.ticket} 已平仓`)
                    await store.fetch()
                  } catch (e: any) {
                    message.error(e?.message || '平仓失败')
                  }
                  loadingClose.value = null
                }
              })
            }
          }, { default: () => '平仓' }),
        ]
      })
    }
  },
]

// 策略颜色映射（与持仓保持一致）
const strategyColors: Record<string, string> = {
  'H1_v6_hybrid': '#2080f0',
  'M30_rsi_bb': '#f0a020',
  'sanqing_h1': '#9220f0',
  'gold_auto_research': '#20c080',
  'bakome_backup': '#808080',
  'xaubot_backup': '#808080',
}

const exitReasonLabels: Record<string, string> = {
  'strategy_exit': '策略出场',
  'mt4_history': 'MT4历史',
  'stop_loss': '止损',
  'take_profit': '止盈',
}

// 最近成交（精简列）
const tradeColumns = [
  { title: 'Ticket', key: 'ticket', width: 70 },
  {
    title: '策略', key: 'strategy', width: 100,
    render(row: any) {
      const name = row.strategy || row.comment || ''
      const color = strategyColors[name] || '#808080'
      return h(NTag, { color: { color, textColor: '#fff' }, size: 'small' },
        { default: () => name || '-' }
      )
    }
  },
  {
    title: '方向', key: 'order_type', width: 55,
    render(row: any) {
      const isBuy = row.order_type?.includes('BUY')
      return h(NTag, { type: isBuy ? 'success' : 'error', size: 'small' },
        { default: () => isBuy ? '多' : '空' }
      )
    }
  },
  { title: '手数', key: 'volume', width: 45 },
  { title: '开仓价', key: 'entry_price', width: 85,
    render(row: any) { return row.entry_price?.toFixed(2) }
  },
  { title: '平仓价', key: 'exit_price', width: 85,
    render(row: any) { return row.exit_price?.toFixed(2) }
  },
  {
    title: '盈亏', key: 'pnl', width: 80,
    render(row: any) {
      const val = row.pnl ?? 0
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  {
    title: '净盈亏', key: 'net_pnl', width: 80,
    render(row: any) {
      const val = (row.pnl ?? 0) + (row.swap ?? 0) + (row.commission ?? 0)
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  { title: '持仓', key: 'hold_seconds', width: 60,
    render(row: any) {
      const sec = row.hold_seconds ?? 0
      if (sec < 60) return `${sec}s`
      if (sec < 3600) return `${Math.round(sec / 60)}m`
      return `${(sec / 3600).toFixed(1)}h`
    }
  },
  {
    title: '出场原因', key: 'exit_reason', width: 85,
    render(row: any) {
      const reason = row.exit_reason || ''
      const label = exitReasonLabels[reason] || reason || '-'
      const type = reason === 'stop_loss' ? 'error' : reason === 'take_profit' ? 'success' : 'default'
      return h(NTag, { size: 'small', type }, { default: () => label })
    }
  },
  { title: '平仓时间', key: 'close_time', width: 130 },
]

async function handleModify() {
  if (editingTicket.value == null) return
  loadingModify.value = true
  try {
    await modifyPosition(editingTicket.value, editSl.value, editTp.value)
    message.success(`#${editingTicket.value} SL/TP 已更新`)
    editingTicket.value = null
    await store.fetch()
  } catch (e: any) {
    message.error(e?.message || '修改失败')
  }
  loadingModify.value = false
}
</script>

<template>
  <n-space vertical size="large">
    <!-- 账户信息（共用组件） -->
    <AccountPanel />

    <div style="display: flex; justify-content: space-between; align-items: center;">
      <n-h2 style="margin:0;">持仓管理</n-h2>
      <n-space size="small">
        <n-tag :bordered="false" type="success">多头 {{ store.longCount }}</n-tag>
        <n-tag :bordered="false" type="error">空头 {{ store.shortCount }}</n-tag>
        <n-tag :bordered="false" :type="store.totalProfit >= 0 ? 'success' : 'error'">
         汇总 ${{ store.totalProfit.toFixed(2) }}
        </n-tag>
      </n-space>
    </div>

    <!-- 加载态 -->
    <n-data-table v-if="store.loading" :columns="columns" :data="[]" :loading="true" :bordered="true" :max-height="600" />
    <!-- 空态 -->
    <n-empty v-else-if="store.items.length === 0" description="暂无持仓">
      <template #extra>
        <n-text depth="3">启动引擎后自动获取 MT4 持仓数据</n-text>
      </template>
    </n-empty>
    <!-- 错误态 -->
    <n-alert v-else-if="store.error" type="error" :title="store.error" closable />
    <!-- 数据态 -->
    <n-data-table v-else :columns="columns" :data="store.items" :bordered="true"
                  :max-height="600" striped :single-line="false"
                  v-model:expanded-row-keys="expandedRowKeys"
                  :row-key="(row: any) => row.ticket" />

    <!-- 最近成交 -->
    <n-card title="最近成交" size="small">
      <template #header-extra>
        <n-space size="small">
          <n-tag :bordered="false" type="info">共 {{ tradeStore.items.length }} 笔</n-tag>
          <n-button size="tiny" secondary circle type="primary" @click="openFullHistory">
            <template #icon><span style="font-weight:bold;font-size:16px;">+</span></template>
          </n-button>
        </n-space>
      </template>
      <n-data-table v-if="tradeStore.loading" :columns="tradeColumns" :data="[]" :loading="true" :bordered="true" :max-height="240" />
      <n-empty v-else-if="tradeStore.items.length === 0" description="暂无历史成交">
        <template #extra><n-text depth="3">启动引擎后自动记录已平仓订单</n-text></template>
      </n-empty>
      <n-alert v-else-if="tradeStore.error" type="error" :title="tradeStore.error" closable />
      <n-data-table v-else :columns="tradeColumns" :data="tradeStore.items" :bordered="true"
                    :max-height="240" striped :single-line="false" />
    </n-card>

    <!-- 全部历史成交弹窗 -->
    <n-modal v-model:show="showHistoryModal" preset="card" title="全部历史成交"
             :style="{ maxWidth: '95vw', maxHeight: '90vh' }" size="large" closable>
      <n-data-table :columns="tradeColumns" :data="fullHistory" :bordered="true" :loading="loadingFullHistory"
                    :max-height="560" striped :single-line="false" virtual-scroll />
    </n-modal>

    <!-- 修改 SL/TP 抽屉 -->
    <n-drawer v-model:show="showDrawer" :width="360" placement="right">
      <n-drawer-content :title="`修改 SL/TP - #${editingTicket}`" closable @close="editingTicket = null">
        <n-space vertical size="large">
          <n-form-item label="止损 (SL)">
            <n-input-number v-model:value="editSl" :step="0.01" style="width:100%;" />
          </n-form-item>
          <n-form-item label="止盈 (TP)">
            <n-input-number v-model:value="editTp" :step="0.01" style="width:100%;" />
          </n-form-item>
          <n-button type="primary" :loading="loadingModify" @click="handleModify" block>
            确认修改
          </n-button>
        </n-space>
      </n-drawer-content>
    </n-drawer>
  </n-space>
</template>
