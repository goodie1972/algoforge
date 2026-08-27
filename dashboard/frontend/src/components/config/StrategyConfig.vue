<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'

const store = useConfigStore()
const message = useMessage()
const { t } = useI18n()

interface StrategyMeta {
  id: string
  name: string
  display: string
  file: string
  backup_file: string | null
  default_magic: number
  default_timeframe: string
}

interface PoolEntry {
  enabled: boolean
  magic: number
  timeframe: string
  max_positions: number
  double_first: boolean
}

const allStrategies = ref<StrategyMeta[]>([])
const pool = ref<Record<string, PoolEntry>>({})
const expanded = ref<Set<string>>(new Set())
const loading = ref(true)
const saving = ref(false)

const timeframes = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1']

const enabledCount = computed(() =>
  Object.values(pool.value).filter(p => p.enabled).length
)

onMounted(async () => {
  let fetched: StrategyMeta[] = []
  try {
    const res = await fetch('/api/strategies/available')
    const data = await res.json()
    fetched = data.strategies || []
  } catch (e) {
    console.error('获取策略清单失败', e)
  }

  await store.fetch()
  const existing = store.items.strategy_pool || {}

  const merged: Record<string, PoolEntry> = {}
  for (const meta of fetched) {
    const curr = (existing as any)[meta.id]
    merged[meta.id] = {
      enabled: curr?.enabled !== undefined ? curr.enabled : false,
      magic: curr?.magic || meta.default_magic,
      timeframe: curr?.timeframe || meta.default_timeframe,
      max_positions: curr?.max_positions ?? 1,
      double_first: curr?.double_first ?? false,
    }
  }
  pool.value = merged
  allStrategies.value = fetched
  loading.value = false
})

function toggleExpand(id: string) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
  expanded.value = new Set(expanded.value)
}

async function savePool() {
  saving.value = true
  try {
    const payload: Record<string, any> = {}
    for (const [id, cfg] of Object.entries(pool.value)) {
      payload[id] = {
        enabled: cfg.enabled,
        magic: cfg.magic,
        timeframe: cfg.timeframe,
        max_positions: cfg.enabled ? (cfg.max_positions || 1) : 0,
        double_first: cfg.double_first,
      }
    }
    await store.updateStrategyPool(payload)
    message.success(t('strategy.saved_pool'))
  } catch (e: any) {
    message.error(t('common.failed') + ': ' + (e.message || '--'))
  }
  saving.value = false
}
</script>

<template>
  <n-space vertical size="large">
    <n-alert type="info" :bordered="false">
      {{ $t('strategy.pool_summary', { total: allStrategies.length, enabled: enabledCount }) }}
    </n-alert>

    <n-spin :show="loading">
      <n-empty v-if="!loading && !allStrategies.length" :description="$t('strategy.no_strategies')" />

      <n-grid :cols="2" :x-gap="12" :y-gap="12">
        <n-grid-item v-for="meta in allStrategies" :key="meta.id">
          <div style="border: 1px solid var(--n-border-color); border-radius: 8px; overflow: hidden;">
            <div style="display: flex; align-items: center; padding: 8px 12px;
              background: pool[meta.id]?.enabled ? 'var(--n-color-pressed)' : 'transparent';
              cursor: pointer;">
              <n-switch :value="pool[meta.id]?.enabled"
                @update:value="pool[meta.id].enabled = !pool[meta.id].enabled"
                size="small" @click.stop />
              <span style="flex: 1; margin-left: 8px; font-weight: 500; font-size: 13px;">
                {{ meta.display }}
                <n-text depth="3" style="font-size: 11px; margin-left: 6px;">{{ meta.name }}</n-text>
              </span>
              <n-tag v-if="pool[meta.id]?.enabled" type="success" size="small">{{ $t('strategy.enabled') }}</n-tag>
              <n-tag v-else type="default" size="small">{{ $t('strategy.disabled') }}</n-tag>
              <n-button text size="tiny" style="margin-left: 8px;" @click.stop="toggleExpand(meta.id)">
                {{ expanded.has(meta.id) ? $t('strategy.collapse') : $t('strategy.expand') }}
              </n-button>
            </div>

            <div v-if="expanded.has(meta.id)"
              style="padding: 12px 16px; border-top: 1px solid var(--n-border-color);">
              <n-grid :cols="2" :x-gap="12" :y-gap="8">
                <n-grid-item>
                  <n-form-item :label="$t('strategy.magic')" label-placement="left" size="small">
                    <app-input-number v-model:value="pool[meta.id].magic" :min="100000" :max="999999"
                      style="width: 30px;" size="small" />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item>
                  <n-form-item :label="$t('strategy.timeframe')" :label-placement="'top'" size="small">
                    <n-select v-model:value="pool[meta.id].timeframe"
                      :options="timeframes.map(t => ({ label: t, value: t }))" size="small" />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item>
                  <n-form-item :label="$t('strategy.double_first')" :label-placement="'top'" size="small">
                    <n-switch v-model:value="pool[meta.id].double_first" size="small" />
                  </n-form-item>
                </n-grid-item>
              </n-grid>
            </div>
          </div>
        </n-grid-item>
      </n-grid>

      <n-button type="primary" :loading="saving" @click="savePool" block size="large" :disabled="loading">
        {{ $t('strategy.save') }}
      </n-button>
    </n-spin>
  </n-space>
</template>
