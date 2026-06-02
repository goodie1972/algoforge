<script setup lang="ts">
import { ref } from 'vue'
import StrategyPool from '@/components/strategy/StrategyPool.vue'
import BacktestPanel from '@/components/strategy/BacktestPanel.vue'
import BacktestResults from '@/components/strategy/BacktestResults.vue'

const activeTab = ref('pool')
</script>

<template>
  <n-space vertical size="large">
    <n-h2>策略中心</n-h2>

    <n-tabs v-model:value="activeTab" type="line" animated>
      <n-tab-pane name="pool" tab="策略组合">
        <StrategyPool />
      </n-tab-pane>
      <n-tab-pane name="backtest" tab="回测">
        <BacktestPanel />
      </n-tab-pane>
      <n-tab-pane name="results" tab="回测记录">
        <BacktestResults />
      </n-tab-pane>
    </n-tabs>
  </n-space>
</template>
