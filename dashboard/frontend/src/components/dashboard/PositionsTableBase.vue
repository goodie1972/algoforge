<script setup lang="ts">
import { h, ref, computed } from 'vue'
import { usePositionStore } from '@/stores/positions'
import { useMessage, useDialog, NButton, NTag, NSpace, NInputNumber, NDataTable, NEmpty, NText, NAlert, NDrawer, NDrawerContent, NFormItem } from 'naive-ui'
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
const expandedRowKeys = ref<(string | number)[]>([])

function renderPosExpand(row: any) {
  return h('div', { style: 'padding: 12px 24px; font-size: 13px; line-height: 1.8; display: grid; grid-template-columns: 1fr 1fr; gap: 16px;' }, [
    h('div', {}, [
      h('div', { style: 'font-weight: 700; margin-bottom: 8px; color: #0ecb81;' }, '开仓信息'),
      h('div', {}, `Magic: ${row.magic || '-'}`),
      h('div', {}, `策略名: ${row.comment || row._strategy_name || '-'}`),
      h('div', {}, `开仓时间: ${row.open_time ? new Date((typeof row.open_time === 'number' ? row.open_time : parseInt(row.open_time)) * 1000).toLocaleString() : '-'}`),
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
  { type: 'expand' as const, width: 30, renderExpand: renderPosExpand },
  { title: 'Ticket', key: 'ticket', width: 80 },
  {
    title: '策略', key: 'strategy', width: 150,
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
    title: '方向', key: 'order_type', width: 40,
    render(row: any) {
      const isBuy = row.order_type?.includes('BUY')
      return h(NTag, { type: isBuy ? 'success' : 'error', size: 'small' },
        { default: () => isBuy ? '多' : '空' }
      )
    }
  },
  { title: '手数', key: 'volume', width: 40 },
  { title: '开仓价', key: 'open_price', width: 80,
    render(row: any) { return row.open_price?.toFixed(2) }
  },
  { title: '现价', key: 'current_price', width: 80,
    render(row: any) { return row.current_price?.toFixed(2) }
  },
  { title: '止损', key: 'stop_loss', width: 80,
    render(row: any) { return row.stop_loss || '-' }
  },
  { title: '止盈', key: 'take_profit', width: 80,
    render(row: any) { return row.take_profit || '-' }
  },
  { title: '开仓时间', key: 'open_time', width: 120,
    render(row: any) {
      if (!row.open_time) return '-'
      const ts = typeof row.open_time === 'number' ? row.open_time : parseInt(row.open_time)
      if (isNaN(ts)) return row.open_time
      return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
    }
  },
  {
    title: '盈亏', key: 'profit', width: 80,
    render(row: any) {
      const val = row.profit ?? 0
      return h('span', { style: { color: val >= 0 ? '#0ecb81' : '#f6465d', fontWeight: 700 } },
        `${val >= 0 ? '+' : ''}$${val.toFixed(2)}`
      )
    }
  },
  {
    title: '操作', key: 'actions', width: 135,
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
  <div>
    <!-- 加载态 -->
    <n-data-table v-if="store.loading" :columns="columns" :data="[]" :loading="true" :bordered="true" :max-height="600" />
    <!-- 空态 -->
    <n-empty v-else-if="store.items.length === 0" description="暂无持仓">
      <template #extra>
        <n-text depth="3">启动引擎后自动获取持仓数据</n-text>
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
      <n-drawer-content :title="`修改 SL/TP - #${editingTicket}`" closable @close="editingTicket = null">
        <n-space vertical size="large">
          <n-form-item label="止损 (SL)">
            <app-input-number v-model:value="editSl" :step="0.01" style="width:100%;" />
          </n-form-item>
          <n-form-item label="止盈 (TP)">
            <app-input-number v-model:value="editTp" :step="0.01" style="width:100%;" />
          </n-form-item>
          <n-button type="primary" :loading="loadingModify" @click="handleModify" block>
            确认修改
          </n-button>
        </n-space>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>
