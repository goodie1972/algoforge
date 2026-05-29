<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useSignalStore } from '@/stores/signals'
import { usePriceStore } from '@/stores/prices'
import { useConfigStore } from '@/stores/config'

const signalStore = useSignalStore()
const priceStore = usePriceStore()
const configStore = useConfigStore()

const strategyLabels: Record<string, string> = {
  double_ma: '双均线',
  atr_breakout: 'ATR 突破',
  combined: '双确认',
  rsi_bollinger: 'RSI+BB',
  stoch_bollinger: 'Stoch+BB',
}

const activeStrategies = computed(() => {
  const pool = configStore.items.strategy_pool || {}
  return Object.entries(pool)
    .filter(([, cfg]: [string, any]) => cfg.enabled !== false)
    .map(([name, cfg]: [string, any]) => ({
      name,
      label: strategyLabels[name] || name,
      magic: cfg.magic || 0,
      timeframe: cfg.timeframe || 'H1',
    }))
})

onMounted(() => configStore.fetch())
</script>

<template>
  <n-card title="策略信号" size="small">
    <n-space vertical>

      <!-- 策略池列表 -->
      <div v-for="s in activeStrategies" :key="s.name"
        style="display: flex; align-items: center; justify-content: space-between;
          padding: 6px 8px; border-radius: 6px; background: var(--n-color-embedded);">
        <n-tag :type="s.name === 'stoch_bollinger' ? 'warning' : 'success'" size="small">
          {{ s.label }}
        </n-tag>
        <n-space size="small">
          <n-text depth="3" style="font-size: 11px;">TF:{{ s.timeframe }}</n-text>
          <n-text depth="3" style="font-size: 11px;">M:{{ s.magic }}</n-text>
        </n-space>
      </div>

      <n-divider style="margin: 4px 0;" />

      <!-- 信号指示 -->
      <n-card size="small" :bordered="true" style="text-align: center;">
        <n-h2 style="margin: 0;" prefix="bar">
          <n-text :type="signalStore.signal === 'BUY' ? 'success' : signalStore.signal === 'SELL' ? 'error' : 'default'"
                  style="font-size: 24px;">
            {{ signalStore.signal || '等待信号' }}
          </n-text>
        </n-h2>
        <n-text v-if="signalStore.timestamp" depth="3" style="font-size: 12px;">
          {{ signalStore.timestamp }}
        </n-text>
      </n-card>

      <!-- 报价 -->
      <n-descriptions :column="2" size="small" label-placement="left" bordered>
        <n-descriptions-item label="当前价格">
          <span class="price-gold">{{ priceStore.midPrice.toFixed(2) }}</span>
        </n-descriptions-item>
        <n-descriptions-item label="买/卖价">
          {{ priceStore.bid.toFixed(2) }} / {{ priceStore.ask.toFixed(2) }}
        </n-descriptions-item>
        <n-descriptions-item label="点差">
          {{ priceStore.spread.toFixed(2) }}
        </n-descriptions-item>
        <n-descriptions-item label="运行策略">
          <n-text>{{ activeStrategies.length }} 个</n-text>
        </n-descriptions-item>
      </n-descriptions>
    </n-space>
  </n-card>
</template>
