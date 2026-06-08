<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()
const saving = ref(false)

interface StrategyCfg {
  enabled: boolean
  magic: number
  timeframe: string
  params: Record<string, number>
}

const strategyLabels: Record<string, string> = {
  M30_rsi_bb: 'M30 RSI+BB（当前实盘）',
  H1_v6_hybrid: 'V6 Hybrid [已归档]',
  double_ma: '双均线 [已归档]',
  atr_breakout: 'ATR 突破 [已归档]',
  combined: '双确认 [已归档]',
  rsi_bollinger: 'RSI+BB [已归档]',
  stoch_bollinger: 'Stoch+BB [已归档]',
}

const strategyDefaults: Record<string, { magic: number; timeframe: string; params: Record<string, number> }> = {
  M30_rsi_bb: { magic: 777001, timeframe: 'M30', params: { rsi_os: 30, rsi_ob: 65, bb_std: 2, atr_trail: 4, atr_hard: 3 } },
}

const timeframes = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1']

const pool = ref<Record<string, StrategyCfg>>({})

function buildPool(): Record<string, StrategyCfg> {
  const existing = store.items.strategy_pool || {}
  const result: Record<string, StrategyCfg> = {}
  for (const [name, def] of Object.entries(strategyDefaults)) {
    const curr = (existing as any)[name] || {}
    result[name] = {
      enabled: curr.enabled !== undefined ? curr.enabled : true,
      magic: curr.magic || def.magic,
      timeframe: curr.timeframe || def.timeframe,
      params: { ...def.params, ...(curr.params || {}) },
    }
  }
  return result
}

onMounted(async () => {
  await store.fetch()
  pool.value = buildPool()
})

function toggleStrategy(name: string) {
  pool.value[name].enabled = !pool.value[name].enabled
}

async function save() {
  saving.value = true
  try {
    const payload: Record<string, any> = {}
    for (const [name, cfg] of Object.entries(pool.value)) {
      payload[name] = {
        enabled: cfg.enabled,
        magic: cfg.magic,
        timeframe: cfg.timeframe,
        params: cfg.params,
      }
    }
    await store.updateStrategyPool(payload)
    message.success('策略池已保存，引擎将在下个周期生效')
  } catch (e: any) {
    message.error(e?.message || '保存失败')
  }
  saving.value = false
}
</script>

<template>
  <n-space vertical size="medium">
    <n-text depth="3">启用或禁用策略，配置 Magic 编号和周期。保存后引擎下个 tick 周期生效。</n-text>

    <n-card v-for="(cfg, name) in pool" :key="name" size="small" :bordered="true"
            :style="{ opacity: cfg.enabled ? 1 : 0.5 }">
      <n-space align="center" justify="space-between">
        <n-space align="center">
          <n-switch :value="cfg.enabled" @update:value="toggleStrategy(name)" size="small" />
          <n-text strong>{{ strategyLabels[name] || name }}</n-text>
          <n-tag size="tiny" :bordered="false">{{ name }}</n-tag>
        </n-space>
        <n-space size="small" align="center">
          <n-text depth="3" style="font-size: 12px;">Magic</n-text>
          <n-input-number v-model:value="cfg.magic" size="tiny" :min="100" :max="999999" style="width: 100px;" />
          <n-select v-model:value="cfg.timeframe" :options="timeframes.map(t => ({ label: t, value: t }))"
                    size="tiny" style="width: 72px;" />
        </n-space>
      </n-space>
      <!-- 策略参数 -->
      <n-grid v-if="cfg.enabled" :cols="4" :x-gap="8" style="margin-top: 8px;">
        <n-gi v-for="(val, key) in cfg.params" :key="key">
          <n-text depth="3" style="font-size: 11px;">{{ key }}</n-text>
          <n-input-number v-model:value="cfg.params[key]" size="tiny" :step="1" style="width: 100%;" />
        </n-gi>
      </n-grid>
    </n-card>

    <n-button type="primary" :loading="saving" @click="save" block>保存策略配置</n-button>
  </n-space>
</template>
