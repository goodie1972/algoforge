<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()

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
    message.success('策略池已保存，重启引擎后生效')
  } catch (e: any) {
    message.error('保存失败: ' + (e.message || '未知错误'))
  }
  saving.value = false
}
</script>

<template>
  <n-space vertical size="large">
    <n-alert type="info" :bordered="false">
      策略池：左侧开关控制是否启用该策略，展开可设置各策略的独立参数（Magic/周期/最大持仓/双倍首单）。保存后重启引擎生效。共 {{ allStrategies.length }} 个策略，已启用 {{ enabledCount }} 个。
    </n-alert>

    <n-spin :show="loading">
      <n-empty v-if="!loading && !allStrategies.length" description="未发现可交易策略" />

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
              <n-tag v-if="pool[meta.id]?.enabled" type="success" size="small">已启用</n-tag>
              <n-tag v-else type="default" size="small">未启用</n-tag>
              <n-button text size="tiny" style="margin-left: 8px;" @click.stop="toggleExpand(meta.id)">
                {{ expanded.has(meta.id) ? '收起' : '展开' }}
              </n-button>
            </div>

            <div v-if="expanded.has(meta.id)"
              style="padding: 12px 16px; border-top: 1px solid var(--n-border-color);">
              <n-grid :cols="2" :x-gap="12" :y-gap="8">
                <n-grid-item>
                  <n-form-item label="Magic Number" :label-placement="'top'" size="small">
                    <app-input-number v-model:value="pool[meta.id].magic" :min="100000" :max="999999"
                      style="width:100%;" size="small" />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item>
                  <n-form-item label="时间周期" :label-placement="'top'" size="small">
                    <n-select v-model:value="pool[meta.id].timeframe"
                      :options="timeframes.map(t => ({ label: t, value: t }))" size="small" />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item>
                  <n-form-item label="最大持仓" :label-placement="'top'" size="small">
                    <app-input-number v-model:value="pool[meta.id].max_positions" :min="1" :max="5"
                      style="width:100%;" size="small" />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item>
                  <n-form-item label="双倍首单" :label-placement="'top'" size="small">
                    <n-switch v-model:value="pool[meta.id].double_first" size="small" />
                  </n-form-item>
                </n-grid-item>
              </n-grid>
            </div>
          </div>
        </n-grid-item>
      </n-grid>

      <n-button type="primary" :loading="saving" @click="savePool" block size="large" :disabled="loading">
        保存策略池配置
      </n-button>
    </n-spin>
  </n-space>
</template>
