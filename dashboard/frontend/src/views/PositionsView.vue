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

const columns = [
  { title: 'Ticket', key: 'ticket', width: 90 },
  { title: '品种', key: 'symbol', width: 90 },
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

// 最近成交（精简列）
const tradeColumns = [
  { title: 'Ticket', key: 'ticket', width: 80 },
  {
    title: '方向', key: 'order_type', width: 60,
    render(row: any) {
      const isBuy = row.order_type?.includes('BUY')
      return h(NTag, { type: isBuy ? 'success' : 'error', size: 'small' },
        { default: () => isBuy ? '多' : '空' }
      )
    }
  },
  { title: '手数', key: 'volume', width: 50 },
  { title: '开仓价', key: 'entry_price', width: 90,
    render(row: any) { return row.entry_price?.toFixed(2) }
  },
  { title: '平仓价', key: 'exit_price', width: 90,
    render(row: any) { return row.exit_price?.toFixed(2) }
  },
  {
    title: '盈亏', key: 'pnl', width: 90,
    render(row: any) {
      const val = row.pnl ?? 0
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  {
    title: '净盈亏', key: 'net_pnl', width: 90,
    render(row: any) {
      const val = (row.pnl ?? 0) + (row.swap ?? 0) + (row.commission ?? 0)
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  { title: '持仓', key: 'hold_seconds', width: 70,
    render(row: any) {
      const sec = row.hold_seconds ?? 0
      if (sec < 60) return `${sec}s`
      if (sec < 3600) return `${Math.round(sec / 60)}m`
      return `${(sec / 3600).toFixed(1)}h`
    }
  },
  { title: '出场原因', key: 'exit_reason', width: 80,
    render(row: any) {
      const reason = row.exit_reason || '-'
      return h(NTag, { size: 'small', type: 'default' }, { default: () => reason })
    }
  },
  { title: '平仓时间', key: 'close_time', width: 140 },
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
                  :max-height="600" striped :single-line="false" />

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
