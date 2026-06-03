<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { useMessage, NTag } from 'naive-ui'
import { getEngineStatus, startEngine, stopEngine } from '@/api/client'
import { PlayOutline, StopOutline } from '@vicons/ionicons5'
import { useAccountStore } from '@/stores/account'
import { usePositionStore } from '@/stores/positions'
import { usePriceStore } from '@/stores/prices'
import TradingTerminal from '@/components/dashboard/TradingTerminal.vue'
import StrategySignals from '@/components/dashboard/StrategySignals.vue'
import AccountPanel from '@/components/dashboard/AccountPanel.vue'

const message = useMessage()
const accountStore = useAccountStore()
const positionStore = usePositionStore()
const priceStore = usePriceStore()

const engineStatus = ref<'running' | 'stopped'>('stopped')
const loading = ref(false)

async function refreshStatus() {
  try {
    const st = await getEngineStatus()
    engineStatus.value = st.status === 'running' ? 'running' : 'stopped'
  } catch { /* ignore */ }
}

onMounted(() => {
  refreshStatus()
  accountStore.fetch()
  positionStore.fetch()
  priceStore.fetchPrice()
})

async function toggleEngine() {
  loading.value = true
  try {
    if (engineStatus.value === 'running') {
      await stopEngine()
      engineStatus.value = 'stopped'
      message.success('引擎已停止')
    } else {
      await startEngine()
      engineStatus.value = 'running'
      message.success('引擎启动成功')
    }
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || '操作失败')
  }
  loading.value = false
}

</script>

<template>
  <n-space vertical size="large">
    <!-- 引擎控制栏 -->
    <n-card :bordered="true" size="small">
      <n-space align="center" justify="space-between">
        <n-space align="center">
          <n-tag :type="engineStatus === 'running' ? 'success' : 'default'" round size="medium" :bordered="false">
            <template #icon>
              <n-icon><div :style="{
                width: 8, height: 8, borderRadius: '50%',
                background: engineStatus === 'running' ? '#0ecb81' : '#8b8f97',
              }" /></n-icon>
            </template>
            {{ engineStatus === 'running' ? '引擎运行中' : '引擎已停止' }}
          </n-tag>
        </n-space>
        <n-space align="center" size="small">
          <n-tag :bordered="false" type="success">多头 {{ positionStore.longCount }}</n-tag>
          <n-tag :bordered="false" type="error">空头 {{ positionStore.shortCount }}</n-tag>
          <n-tag :bordered="false" :type="positionStore.totalProfit >= 0 ? 'success' : 'error'">
            浮动盈亏 ${{ positionStore.totalProfit.toFixed(2) }}
          </n-tag>
          <n-button :type="engineStatus === 'running' ? 'error' : 'primary'"
                    :loading="loading" @click="toggleEngine">
            <template #icon>
              <n-icon><component :is="engineStatus === 'running' ? StopOutline : PlayOutline" /></n-icon>
            </template>
            {{ engineStatus === 'running' ? '停止引擎' : '启动引擎' }}
          </n-button>
        </n-space>
      </n-space>
    </n-card>

    <!-- 账户概览（共用组件） -->
    <AccountPanel />

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
            { title: 'Ticket', key: 'ticket', width: 90 },
            { title: '方向', key: 'order_type', width: 70,
              render(row: any) {
                const isBuy = row.order_type?.includes('BUY')
                return h(NTag, { type: isBuy ? 'success' : 'error', size: 'small' },
                  { default: () => isBuy ? '多' : '空' }
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
        />
      </template>
    </n-card>
  </n-space>
</template>
