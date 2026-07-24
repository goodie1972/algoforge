<script setup lang="ts">
import { onMounted } from 'vue'
import { usePositionStore } from '@/stores/positions'
import { usePriceStore } from '@/stores/prices'
import TradingTerminal from '@/components/dashboard/TradingTerminal.vue'
import StrategySignals from '@/components/dashboard/StrategySignals.vue'
import PositionsTableBase from '@/components/dashboard/PositionsTableBase.vue'

const positionStore = usePositionStore()
const priceStore = usePriceStore()

onMounted(() => {
  positionStore.fetch()
  priceStore.fetchPrice()
})
</script>

<template>
  <n-space vertical size="large">
    <!-- 图表 + 信号 -->
    <n-grid :cols="3" :x-gap="16">
      <n-gi :span="2"><TradingTerminal /></n-gi>
      <n-gi><StrategySignals /></n-gi>
    </n-grid>

    <!-- 持仓摘要 -->
    <n-card size="small" :bordered="true" title="当前持仓">
      <PositionsTableBase />
    </n-card>
  </n-space>
</template>
