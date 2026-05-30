<script setup lang="ts">
import { computed } from 'vue'
import { useConfigStore } from '@/stores/config'

const store = useConfigStore()

const strategyLabels: Record<string, string> = {
  double_ma: '双均线',
  atr_breakout: 'ATR 突破',
  combined: '双确认',
  rsi_bollinger: 'RSI+BB',
  stoch_bollinger: 'Stoch+BB',
}

const activeStrategies = computed(() => {
  const pool = store.items.strategy_pool || {}
  return Object.entries(pool)
    .filter(([, cfg]: [string, any]) => cfg.enabled !== false)
    .map(([name, cfg]: [string, any]) => ({
      name,
      label: strategyLabels[name] || name,
      magic: cfg.magic || 0,
      timeframe: cfg.timeframe || 'H1',
    }))
})
</script>

<template>
  <n-grid :cols="2" :x-gap="24">
    <!-- 左列：MT4 连接 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-divider title-position="left">MT4 连接</n-divider>
        <n-descriptions :column="1" label-placement="left" bordered size="small">
          <n-descriptions-item label="MT4 地址">127.0.0.1:23232</n-descriptions-item>
          <n-descriptions-item label="交易品种">XAUUSD</n-descriptions-item>
        </n-descriptions>
        <n-alert type="info" :bordered="false" size="small">
          MT4 连接参数在 config/settings.py 中配置，修改后重启引擎生效。
        </n-alert>
      </n-space>
    </n-grid-item>

    <!-- 右列：已启用策略 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-divider title-position="left">已启用策略</n-divider>

        <n-empty v-if="activeStrategies.length === 0" description="尚未启用任何策略" size="small" />

        <n-descriptions v-else :column="1" label-placement="left" bordered size="small">
          <n-descriptions-item v-for="s in activeStrategies" :key="s.name" :label="s.label">
            <n-space size="small">
              <n-tag size="small" type="info">Magic: {{ s.magic }}</n-tag>
              <n-tag size="small">TF: {{ s.timeframe }}</n-tag>
            </n-space>
          </n-descriptions-item>
        </n-descriptions>
      </n-space>
    </n-grid-item>
  </n-grid>
</template>
