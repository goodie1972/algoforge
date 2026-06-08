<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()

const pool = ref<Record<string, any>>({})
const expanded = ref<Set<string>>(new Set())

onMounted(() => {
  pool.value = { ...(store.items.strategy_pool || {}) }
})

function toggleStrategy(name: string) {
  if (pool.value[name]) {
    delete pool.value[name]
  } else {
    const defaults: Record<string, { magic: number; timeframe: string }> = {
      M30_rsi_bb: { magic: 777001, timeframe: 'M30' },
      double_ma: { magic: 101, timeframe: 'H1' },
      atr_breakout: { magic: 102, timeframe: 'H1' },
      combined: { magic: 103, timeframe: 'H1' },
      rsi_bollinger: { magic: 777777, timeframe: 'H1' },
      stoch_bollinger: { magic: 888888, timeframe: 'H4' },
    }
    const d = defaults[name] || { magic: 666666, timeframe: 'H1' }
    pool.value[name] = {
      enabled: true,
      magic: d.magic,
      timeframe: d.timeframe,
      double_first: true,
      max_positions: 2,
    }
  }
  pool.value = { ...pool.value }
}

function isEnabled(name: string) {
  return !!pool.value[name]
}

function toggleExpand(name: string) {
  if (expanded.value.has(name)) {
    expanded.value.delete(name)
  } else {
    expanded.value.add(name)
  }
  expanded.value = new Set(expanded.value)
}

function isExpanded(name: string) {
  return expanded.value.has(name)
}

async function updatePoolParam(name: string, key: string, value: any) {
  if (!pool.value[name]) return
  pool.value[name] = { ...pool.value[name], [key]: value }
  pool.value = { ...pool.value }
}

async function savePool() {
  try {
    await store.updateStrategyPool(pool.value)
    message.success('策略池已保存，重启引擎后生效')
  } catch (e: any) {
    message.error('保存失败: ' + (e.message || '未知错误'))
  }
}

const strategyOptions = [
  { label: 'M30 RSI+BB（当前实盘）', value: 'M30_rsi_bb' },
  { label: '— 历史策略 —', value: '' },
  { label: 'V6 Hybrid（已归档）', value: 'H1_v6_hybrid' },
  { label: '双均线', value: 'double_ma' },
  { label: 'ATR 突破', value: 'atr_breakout' },
  { label: '双确认', value: 'combined' },
  { label: 'RSI+布林带', value: 'rsi_bollinger' },
  { label: 'Stoch+布林带', value: 'stoch_bollinger' },
]

const timeframeOptions = [
  { label: 'M1', value: 'M1' }, { label: 'M5', value: 'M5' },
  { label: 'M15', value: 'M15' }, { label: 'M30', value: 'M30' },
  { label: 'H1', value: 'H1' }, { label: 'H4', value: 'H4' },
  { label: 'D1', value: 'D1' },
]
</script>

<template>
  <n-space vertical size="large">
    <n-alert type="info" :bordered="false">
      策略池：勾选要运行的策略，展开可设置各策略的独立参数。保存后重启引擎生效。
    </n-alert>

    <!-- 策略列表 2 列 -->
    <n-grid :cols="2" :x-gap="12" :y-gap="12">
      <n-grid-item v-for="opt in strategyOptions" :key="opt.value">
        <div style="border: 1px solid var(--n-border-color); border-radius: 8px; overflow: hidden;">
          <div style="display: flex; align-items: center; padding: 8px 12px;
            background: isEnabled(opt.value) ? 'var(--n-color-pressed)' : 'transparent';
            cursor: pointer;" @click="toggleExpand(opt.value)">
            <n-checkbox :checked="isEnabled(opt.value)"
              @update:checked="() => toggleStrategy(opt.value)"
              @click.stop />
            <span style="flex: 1; margin-left: 8px; font-weight: 500; font-size: 13px;">{{ opt.label }}</span>
            <n-tag v-if="isEnabled(opt.value)" type="success" size="small">已启用</n-tag>
            <n-tag v-else type="default" size="small">未启用</n-tag>
            <n-button text size="tiny" style="margin-left: 8px;">
              {{ isExpanded(opt.value) ? '收起' : '展开' }}
            </n-button>
          </div>

          <div v-if="isExpanded(opt.value) && isEnabled(opt.value)"
            style="padding: 12px 16px; border-top: 1px solid var(--n-border-color);">
            <n-grid :cols="2" :x-gap="12" :y-gap="8">
              <n-grid-item>
                <n-form-item label="Magic Number" :label-placement="'top'" size="small">
                  <n-input-number v-model:value="pool[opt.value].magic" :min="100000" :max="999999"
                    @update:value="(v: any) => updatePoolParam(opt.value, 'magic', v)" style="width:100%;" size="small" />
                </n-form-item>
              </n-grid-item>
              <n-grid-item>
                <n-form-item label="时间周期" :label-placement="'top'" size="small">
                  <n-select v-model:value="pool[opt.value].timeframe" :options="timeframeOptions"
                    @update:value="(v: string) => updatePoolParam(opt.value, 'timeframe', v)" size="small" />
                </n-form-item>
              </n-grid-item>
              <n-grid-item>
                <n-form-item label="最大持仓" :label-placement="'top'" size="small">
                  <n-input-number v-model:value="pool[opt.value].max_positions" :min="1" :max="5"
                    @update:value="(v: any) => updatePoolParam(opt.value, 'max_positions', v)" style="width:100%;" size="small" />
                </n-form-item>
              </n-grid-item>
              <n-grid-item>
                <n-form-item label="双倍首单" :label-placement="'top'" size="small">
                  <n-switch v-model:value="pool[opt.value].double_first"
                    @update:value="(v: boolean) => updatePoolParam(opt.value, 'double_first', v)" />
                </n-form-item>
              </n-grid-item>
            </n-grid>
          </div>
        </div>
      </n-grid-item>
    </n-grid>

    <n-button type="primary" @click="savePool" block>
      保存策略池配置
    </n-button>
  </n-space>
</template>
