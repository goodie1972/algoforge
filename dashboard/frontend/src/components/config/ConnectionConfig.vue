<script setup lang="ts">
import { computed } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useI18n } from 'vue-i18n'

const store = useConfigStore()
const { t } = useI18n()

const strategyLabels: Record<string, string> = {
  H1_v6_hybrid: 'V6 Hybrid',
  M30_rsi_bb: 'M30 RSI+BB',
  double_ma: t('strategy.name.double_ma') + t('strategy.archived_suffix'),
  atr_breakout: t('strategy.name.atr_breakout') + t('strategy.archived_suffix'),
  combined: t('strategy.name.combined') + t('strategy.archived_suffix'),
  rsi_bollinger: t('strategy.name.rsi_bollinger') + t('strategy.archived_suffix'),
  stoch_bollinger: t('strategy.name.stoch_bollinger') + t('strategy.archived_suffix'),
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
        <n-divider title-position="left">{{ $t('config.mt4_title') }}</n-divider>
        <n-descriptions :column="1" label-placement="left" bordered size="small">
          <n-descriptions-item :label="$t('config.mt4_address')">127.0.0.1:23232</n-descriptions-item>
          <n-descriptions-item :label="$t('config.mt4_symbol')">XAUUSD</n-descriptions-item>
        </n-descriptions>
        <n-alert type="info" :bordered="false" size="small">
          {{ $t('config.mt4_desc') }}
        </n-alert>
      </n-space>
    </n-grid-item>

    <!-- 右列：已启用策略 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-divider title-position="left">{{ $t('config.enabled_strategies') }}</n-divider>

        <n-empty v-if="activeStrategies.length === 0" :description="$t('config.no_strategies')" size="small" />

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
