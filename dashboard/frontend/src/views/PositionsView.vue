<script setup lang="ts">
import { h, ref, computed } from 'vue'
import { usePositionStore } from '@/stores/positions'
import { useMessage, useDialog, NButton, NTag, NSpace, NInput, NDataTable } from 'naive-ui'
import { closePosition, modifyPosition } from '@/api/client'

const store = usePositionStore()
const message = useMessage()
const dialog = useDialog()
const editingTicket = ref<number | null>(null)
const editSl = ref(0)
const editTp = ref(0)
const loadingClose = ref<number | null>(null)
const loadingModify = ref(false)
const showDrawer = computed(() => editingTicket.value != null)

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
