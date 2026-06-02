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

    <!-- 账户指标卡片 -->
    <n-card size="small" :bordered="true">
      <template #header>
        <n-space align="center">
          <n-text strong>账户概览</n-text>
          <n-tag v-if="accountStore.error && accountStore.info" size="tiny" type="warning" :bordered="false">同步延迟</n-tag>
        </n-space>
      </template>
      <template v-if="accountStore.loading && !accountStore.info">
        <n-skeleton text :repeat="1" />
      </template>
      <template v-else-if="!accountStore.info && accountStore.error">
        <n-result status="error" title="获取账户信息失败" :description="accountStore.error" size="small">
          <template #footer>
            <n-button size="small" @click="accountStore.fetch()">重试</n-button>
          </template>
        </n-result>
      </template>
      <template v-else-if="!accountStore.info">
        <n-result status="info" title="等待连接" description="MT4 未连接，启动引擎后自动获取" size="small" />
      </template>
      <template v-else>
        <n-grid :cols="5" :x-gap="16">
          <n-gi>
            <n-statistic label="余额" tabular-nums>
              <span class="price-gold">${{ accountStore.info.balance.toFixed(2) }}</span>
            </n-statistic>
          </n-gi>
          <n-gi>
            <n-statistic label="净值" tabular-nums>
              <span :class="(accountStore.info.equity ?? 0) >= accountStore.info.balance ? 'price-up' : 'price-down'">
                ${{ (accountStore.info.equity ?? 0).toFixed(2) }}
              </span>
            </n-statistic>
          </n-gi>
          <n-gi>
            <n-statistic label="已用保证金" tabular-nums>
              ${{ accountStore.info.margin.toFixed(2) }}
            </n-statistic>
          </n-gi>
          <n-gi>
            <n-statistic label="可用保证金" tabular-nums>
              ${{ accountStore.info.free_margin.toFixed(2) }}
            </n-statistic>
          </n-gi>
          <n-gi>
            <n-statistic label="当前报价" tabular-nums>
              <span class="price-gold">{{ priceStore.midPrice.toFixed(2) }}</span>
            </n-statistic>
          </n-gi>
        </n-grid>
      </template>
    </n-card>

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
