<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import StrategyPool from '@/components/strategy/StrategyPool.vue'
import BacktestPanel from '@/components/strategy/BacktestPanel.vue'
import BacktestResults from '@/components/strategy/BacktestResults.vue'

const activeTab = ref('pool')
const { t } = useI18n()
</script>

<template>
  <n-space vertical size="large">
    <n-h2>{{ t('strategy.title') }}</n-h2>

    <n-tabs v-model:value="activeTab" type="line" animated>
      <n-tab-pane name="pool" :tab="t('strategy.tab_pool')">
        <StrategyPool />
      </n-tab-pane>
      <n-tab-pane name="backtest" :tab="t('strategy.tab_backtest')">
        <BacktestPanel />
      </n-tab-pane>
      <n-tab-pane name="results" :tab="t('strategy.tab_records')">
        <BacktestResults />
      </n-tab-pane>
    </n-tabs>
  </n-space>
</template>
