<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { getStrategyColor, getStrategyTextColor } from '@/utils/strategyColors'
import { translateFactor, translateMethod, translateDetail, translateDisplay } from '@/utils/strategyTranslations'

const store = useConfigStore()
const message = useMessage()
const { t, locale } = useI18n()
const saving = ref(false)
const fileInput = ref<HTMLInputElement>()

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

const timeframes = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1']

interface EntryFactor {
  name: string
  score: string
  detail: string
}

interface ExitRow {
  method: string
  normal: string
  widen?: string
}

// 策略进出场逻辑 (与交易终端一致)
interface StratLogic {
  desc: string
  desc_en?: string
  exitWiden?: boolean
  exitNote?: string
  long: { entry: EntryFactor[]; exit: ExitRow[] }
  short: { entry: EntryFactor[]; exit: ExitRow[] }
}

const strategyLogics = ref<Record<string, StratLogic>>({})

function getLogic(name: string): StratLogic | null {
  return strategyLogics.value[name] || null
}

async function fetchLogics() {
  try {
    const res = await fetch('/api/strategies/logics')
    const data = await res.json()
    strategyLogics.value = data.logics || {}
  } catch (e) {
    console.error('获取策略逻辑失败:', e)
  }
}

// 策略颜色由 getStrategyColor(name) 动态分配
// 带 _optimized / _original 后缀的策略自动同色系不同深浅

// 已启用策略
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
  fetchLogics()

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

function toggleStrategy(id: string) {
  if (pool.value[id]) {
    pool.value[id].enabled = !pool.value[id].enabled
  }
}

function toggleExpand(id: string) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
  expanded.value = new Set(expanded.value)
}

function getColor(name: string): string {
  return getStrategyColor(name)
}

function updateMagic(id: string, val: string) {
  const n = parseInt(val, 10)
  if (!isNaN(n) && pool.value[id]) {
    pool.value[id].magic = Math.min(999999, Math.max(100000, n))
  }
}

async function save() {
  saving.value = true
  try {
    // 只传 enabled=true 的到 runtime_config
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
    message.success(t('strategy.saved'))
  } catch (e: any) {
    message.error(e?.message || t('common.failed'))
  }
  saving.value = false
}

async function handleUpload() {
  const input = fileInput.value
  if (!input || !input.files?.length) return
  const file = input.files[0]
  if (!file.name.endsWith('.py')) {
    message.error(t('strategy.only_py') || '只支持 .py 文件')
    return
  }
  const form = new FormData()
  form.append('file', file)
  try {
    const res = await fetch('/api/strategies/upload', { method: 'POST', body: form })
    const data = await res.json()
    if (res.ok) {
      message.success(data.message || '上传成功')
      input.value = ''
      window.location.reload()
    } else {
      message.error(data.detail || '上传失败')
    }
  } catch { message.error('上传失败') }
}

async function handleRemove(name: string) {
  if (!confirm(t('strategy.confirm_remove') + ' ' + name + '?')) return
  try {
    const res = await fetch(`/api/strategies/${name}/remove`, { method: 'POST' })
    const data = await res.json()
    if (res.ok) {
      message.success(data.message)
      window.location.reload()
    } else {
      message.error(data.detail || '删除失败')
    }
  } catch { message.error('删除失败') }
}
</script>

<template>
  <n-space vertical size="medium">
    <n-alert type="info" :bordered="false" closable>
      {{ $t('strategy.pool_summary', { total: allStrategies.length, enabled: enabledCount }) }}
      {{ $t('strategy.pool_hint') }}
    </n-alert>

    <div style="display:flex;gap:8px;margin-bottom:4px;">
      <input ref="fileInput" type="file" accept=".py" style="display:none" @change="handleUpload" />
      <n-button size="small" secondary @click="fileInput?.click()">{{ $t('strategy.import_strategy') }}</n-button>
    </div>

    <n-spin :show="loading">
      <n-empty v-if="!loading && !allStrategies.length" :description="$t('strategy.no_strategies')" />

      <n-card v-for="meta in allStrategies" :key="meta.id" size="small" :bordered="true"
        :style="{
          opacity: pool[meta.id]?.enabled ? 1 : 0.55,
          borderLeft: `4px solid ${getColor(meta.name)}`,
        }">

        <!-- 顶栏: 开关 + 名称 + 标签 + Magic + TF -->
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <n-switch :value="pool[meta.id]?.enabled"
              @update:value="toggleStrategy(meta.id)" size="small" />
            <n-text strong style="font-size: 14px;">{{ locale === 'en-US' ? translateDisplay(meta.display) : meta.display }}</n-text>
            <n-tag :color="{ color: getColor(meta.name), textColor: getStrategyTextColor(meta.name) }" size="tiny" style="font-weight: 600; font-size: 14px; padding: 2px 7px;">
              {{ meta.name }}
            </n-tag>
            <n-tag v-if="meta.backup_file" size="tiny" :bordered="false" type="info">
              {{ meta.backup_file }}
            </n-tag>
          </div>

          <div style="display: flex; align-items: center; gap: 12px;">
            <n-space size="small" align="center">
              <n-text depth="3" style="font-size: 11px;">{{ $t('strategy.magic') }}</n-text>
              <n-input :value="String(pool[meta.id]?.magic || '')" size="tiny"
                style="width: 76px;" @click.stop
                @update:value="updateMagic(meta.id, $event)" />
            </n-space>
            <n-select v-model:value="pool[meta.id].timeframe"
              :options="timeframes.map(t => ({ label: t, value: t }))"
              size="tiny" style="width: 65px;" @click.stop />
            <n-button text size="tiny" style="font-size: 16px; width: 24px;"
              @click.stop="toggleExpand(meta.id)">
              {{ expanded.has(meta.id) ? '▼' : '▶' }}
            </n-button>
            <n-button text size="tiny" style="color:#f6465d;font-size:12px;width:20px;"
              @click.stop="handleRemove(meta.name)">✕</n-button>
          </div>
        </div>

        <!-- 持仓参数 (展开后显示) -->
        <div v-if="expanded.has(meta.id)" style="margin-top: 6px;">
          <div style="display: flex; gap: 16px; align-items: center; margin-bottom: 8px;">
            <n-space align="center" size="small">
              <n-text depth="3" style="font-size: 11px;">{{ $t('strategy.max_positions') }}</n-text>
              <app-input-number v-model:value="pool[meta.id].max_positions"
                size="tiny" :min="1" :max="5" style="width: 60px;" @click.stop />
            </n-space>
            <n-space align="center" size="small">
              <n-text depth="3" style="font-size: 11px;">{{ $t('strategy.double_first') }}</n-text>
              <n-switch v-model:value="pool[meta.id].double_first" size="small" @click.stop />
            </n-space>
          </div>

          <!-- 进出场逻辑 (双栏: 左做多右做空, 上入场下出场) -->
          <template v-if="getLogic(meta.name)">
            <n-text depth="2" style="font-size: 12px; display: block; margin-bottom: 8px;">
              {{ locale === 'en-US' ? (getLogic(meta.name)!.desc_en || getLogic(meta.name)!.desc) : getLogic(meta.name)!.desc }}
            </n-text>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
              <!-- 做多 (左) -->
              <div style="border-left: 3px solid #0ecb81; padding-left: 8px;">
                <div style="font-weight: 600; color: #0ecb81; font-size: 12px; margin-bottom: 3px;">▲ {{ $t('strategy.long') }}</div>
                <n-table size="small" bordered single-line :style="{ fontSize: '11px' }">
                  <thead>
                    <tr>
                      <th style="width: 20px; text-align: center;">#</th>
                      <th>{{ $t('strategy.factor') }}</th>
                      <th style="width: 34px; text-align: center;">{{ $t('strategy.score') }}</th>
                      <th>{{ $t('strategy.condition') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(f, i) in getLogic(meta.name)!.long.entry" :key="'le'+i">
                      <td style="text-align: center; color: #8b8f97;">{{ i+1 }}</td>
                      <td>{{ locale === 'en-US' ? translateFactor(f.name) : f.name }}</td>
                      <td style="text-align: center;">
                        <span v-if="f.score" style="display:inline-block; padding:0 3px; background:#f0a020; color:#fff; font-weight:700; font-size:10px; border-radius:2px;">{{ f.score }}</span>
                      </td>
                      <td>{{ locale === 'en-US' ? translateDetail(f.detail) : f.detail }}</td>
                    </tr>
                  </tbody>
                </n-table>
                <n-table size="small" bordered single-line :style="{ fontSize: '10px' }" style="margin-top: 3px;">
                  <thead>
                    <tr>
                      <th style="width:16px;text-align:center;">#</th>
                      <th>{{ $t('strategy.exit_mode') }}</th>
                      <th>{{ $t('strategy.normal_mode') }}</th>
                      <th v-if="getLogic(meta.name)!.exitWiden" style="text-align:center;">{{ $t('strategy.wide_mode') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(ex, i) in getLogic(meta.name)!.long.exit" :key="'lx'+i">
                      <td style="text-align:center;color:#8b8f97;">{{ i+1 }}</td>
                      <td>{{ locale === 'en-US' ? translateMethod(ex.method) : ex.method }}</td>
                      <td>{{ locale === 'en-US' ? translateDetail(ex.normal) : ex.normal }}</td>
                      <td v-if="getLogic(meta.name)!.exitWiden" style="text-align:center;">{{ ex.widen || '—' }}</td>
                    </tr>
                  </tbody>
                </n-table>
                <div v-if="getLogic(meta.name)!.exitNote" style="font-size:10px;color:#8b8f97;margin-top:2px;">
                  {{ getLogic(meta.name)!.exitNote }}
                </div>
              </div>

              <!-- 做空 (右) -->
              <div style="border-left: 3px solid #f6465d; padding-left: 8px;">
                <div style="font-weight: 600; color: #f6465d; font-size: 12px; margin-bottom: 3px;">▼ {{ $t('strategy.short') }}</div>
                <n-table size="small" bordered single-line :style="{ fontSize: '11px' }">
                  <thead>
                    <tr>
                      <th style="width: 20px; text-align: center;">#</th>
                      <th>{{ $t('strategy.factor') }}</th>
                      <th style="width: 34px; text-align: center;">{{ $t('strategy.score') }}</th>
                      <th>{{ $t('strategy.condition') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(f, i) in getLogic(meta.name)!.short.entry" :key="'se'+i">
                      <td style="text-align: center; color: #8b8f97;">{{ i+1 }}</td>
                      <td>{{ locale === 'en-US' ? translateFactor(f.name) : f.name }}</td>
                      <td style="text-align: center;">
                        <span v-if="f.score" style="display:inline-block; padding:0 3px; background:#f0a020; color:#fff; font-weight:700; font-size:10px; border-radius:2px;">{{ f.score }}</span>
                      </td>
                      <td>{{ locale === 'en-US' ? translateDetail(f.detail) : f.detail }}</td>
                    </tr>
                  </tbody>
                </n-table>
                <n-table size="small" bordered single-line :style="{ fontSize: '10px' }" style="margin-top: 3px;">
                  <thead>
                    <tr>
                      <th style="width:16px;text-align:center;">#</th>
                      <th>{{ $t('strategy.exit_mode') }}</th>
                      <th>{{ $t('strategy.normal_mode') }}</th>
                      <th v-if="getLogic(meta.name)!.exitWiden" style="text-align:center;">{{ $t('strategy.wide_mode') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(ex, i) in getLogic(meta.name)!.short.exit" :key="'sx'+i">
                      <td style="text-align:center;color:#8b8f97;">{{ i+1 }}</td>
                      <td>{{ locale === 'en-US' ? translateMethod(ex.method) : ex.method }}</td>
                      <td>{{ locale === 'en-US' ? translateDetail(ex.normal) : ex.normal }}</td>
                      <td v-if="getLogic(meta.name)!.exitWiden" style="text-align:center;">{{ ex.widen || '—' }}</td>
                    </tr>
                  </tbody>
                </n-table>
                <div v-if="getLogic(meta.name)!.exitNote" style="font-size:10px;color:#8b8f97;margin-top:2px;">
                  {{ getLogic(meta.name)!.exitNote }}
                </div>
              </div>
            </div>
          </template>
          <div v-else style="font-size:12px; color:#8b8f97; padding:4px 0;">{{ $t('strategy.no_logic') }}</div>
        </div>
      </n-card>

      <n-button type="primary" :loading="saving" @click="save" block size="large"
        :disabled="loading">
        {{ $t('strategy.save') }}
      </n-button>
    </n-spin>
  </n-space>
</template>
