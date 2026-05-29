<script setup lang="ts">
import { computed } from 'vue'
import { useConfigStore } from '@/stores/config'

const store = useConfigStore()

const params = computed(() => ({
  lot_size: store.items.lot_size ?? 0.01,
  max_positions: store.items.max_positions ?? 3,
  max_daily_loss_pct: store.items.max_daily_loss_pct ?? 5.0,
  stop_loss_pips: store.items.stop_loss_pips ?? 50,
  take_profit_pips: store.items.take_profit_pips ?? 100,
  slippage: store.items.slippage ?? 30,
}))

async function update(updates: Record<string, any>) {
  await store.update(updates)
}
</script>

<template>
  <n-space vertical size="large">
    <n-divider title-position="left">仓位管理</n-divider>
    <n-form-item label="每次开仓手数">
      <n-input-number :value="params.lot_size" :min="0.01" :max="10" :step="0.01"
        @update:value="(v: any) => v && update({ lot_size: v })" style="width:100%;" />
    </n-form-item>
    <n-form-item label="最大同时持仓数">
      <n-input-number :value="params.max_positions" :min="1" :max="20"
        @update:value="(v: any) => v && update({ max_positions: v })" style="width:100%;" />
    </n-form-item>

    <n-divider title-position="left">止损止盈</n-divider>
    <n-form-item label="默认止损 (点数)">
      <n-input-number :value="params.stop_loss_pips" :min="10" :max="500"
        @update:value="(v: any) => v && update({ stop_loss_pips: v })" style="width:100%;" />
    </n-form-item>
    <n-form-item label="默认止盈 (点数)">
      <n-input-number :value="params.take_profit_pips" :min="10" :max="1000"
        @update:value="(v: any) => v && update({ take_profit_pips: v })" style="width:100%;" />
    </n-form-item>

    <n-divider title-position="left">风控限制</n-divider>
    <n-form-item label="日内最大亏损 (%)">
      <n-input-number :value="params.max_daily_loss_pct" :min="1" :max="100" :step="0.5"
        @update:value="(v: any) => v && update({ max_daily_loss_pct: v })" style="width:100%;" />
      <template #feedback>到达此亏损比例后自动停止交易至次日</template>
    </n-form-item>
    <n-form-item label="允许滑点 (Points)">
      <n-input-number :value="params.slippage" :min="0" :max="100"
        @update:value="(v: any) => v !== null && update({ slippage: v })" style="width:100%;" />
    </n-form-item>
  </n-space>
</template>
