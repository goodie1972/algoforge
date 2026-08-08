<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TradeStats } from '@/types'

const { t } = useI18n()

const props = defineProps<{
  stats: TradeStats | null
  selectedStrategy: string
  selectedVersion?: string
}>()

const emit = defineEmits<{
  (e: 'select', v: string): void
  (e: 'select-version', v: string): void
}>()

const showCriteria = ref(false)

const strategyNames = computed(() => {
  if (!props.stats) return []
  return Object.keys(props.stats.by_strategy || {})
})

const versionOptions = computed(() => {
  if (!props.stats || !props.selectedStrategy) return []
  const family = props.stats.by_strategy[props.selectedStrategy]
  if (!family?.versions?.length) return []
  return [
    { label: t('radar.all_versions'), value: '' },
    ...family.versions.map((v: any) => ({
      label: `${v.version} (Magic: ${v.magic})`,
      value: String(v.magic),
    })),
  ]
})

const strategy = computed(() => {
  if (!props.stats) return null
  const by = props.stats.by_strategy || {}
  const family = by[props.selectedStrategy]
  if (!family) return null

  if (props.selectedVersion) {
    const version = family.versions.find((v: any) => String(v.magic) === props.selectedVersion)
    return version || null
  }
  return family || null
})

interface ScoreItem {
  label: string
  raw: number | string
  score: number
  max: number
  desc: string
}

const scores = computed<ScoreItem[]>(() => {
  const s = strategy.value
  if (!s) return []
  const total = s.total_trades || 0
  if (total === 0) return []

  const pf = typeof s.profit_factor === 'number' ? s.profit_factor : 0
  const wr = s.win_rate ?? 0
  const ratio = typeof s.ratio_avg_profit_loss === 'number' ? s.ratio_avg_profit_loss : 0
  const consec = s.max_consecutive_losses ?? 0
  const ep = s.expected_payoff ?? 0

  // PF: 0-100 over range 0-4
  const pfScore = Math.min(100, Math.round(pf / 4 * 100))
  // WinRate: 0-100 directly
  const wrScore = Math.min(100, Math.round(wr))
  // AvgWin/AvgLoss ratio: 0-100 over range 0-4
  const ratioScore = Math.min(100, Math.round(ratio / 4 * 100))
  // ConsecLosses: invert, fewer = better
  const consecScore = Math.min(100, Math.max(0, Math.round((1 - consec / 20) * 100)))
  // Expected Payoff: map -20..+20 to 0-100
  const epScore = Math.min(100, Math.max(0, Math.round((ep + 20) / 40 * 100)))

  return [
    { label: 'Profit Factor', raw: pf, score: pfScore, max: 100, desc: t('radar.desc_pf') },
    { label: t('radar.win_rate'), raw: wr, score: wrScore, max: 100, desc: t('radar.desc_win_rate') },
    { label: t('radar.profit_ratio'), raw: ratio, score: ratioScore, max: 100, desc: t('radar.desc_ratio') },
    { label: t('radar.consec_loss_ctrl'), raw: consec, score: consecScore, max: 100, desc: t('radar.desc_consec') },
    { label: t('radar.expected_return'), raw: ep, score: epScore, max: 100, desc: t('radar.desc_ep') },
  ]
})

const totalScore = computed(() => {
  const items = scores.value
  if (!items.length) return 0
  // Weighted: PF 25, WinRate 20, Ratio 25, Consec 15, EP 15 = 100
  const weights = [0.25, 0.20, 0.25, 0.15, 0.15]
  return Math.round(items.reduce((sum, item, i) => sum + item.score * weights[i], 0))
})

const grade = computed(() => {
  const score = totalScore.value
  if (score >= 80) return { label: t('radar.excellent'), color: '#0ecb81' }
  if (score >= 60) return { label: t('radar.good'), color: '#f0b90b' }
  if (score >= 40) return { label: t('radar.pass'), color: '#f0a020' }
  return { label: t('radar.fail'), color: '#f6465d' }
})

// SVG radar chart dimensions
const cx = 160, cy = 160, r = 130
const levels = [0.2, 0.4, 0.6, 0.8, 1.0]

function angle(i: number, total: number) {
  // Start from top (-π/2), clockwise
  return -Math.PI / 2 + (2 * Math.PI * i) / total
}

function point(i: number, total: number, radius: number) {
  const a = angle(i, total)
  return { x: cx + radius * Math.cos(a), y: cy + radius * Math.sin(a) }
}

const axes = computed(() => {
  const items = scores.value
  if (!items.length) return { labels: [], shape: '', area: '', dots: [] }
  const n = items.length

  // Background levels
  const bgLevels = levels.map(l =>
    items.map((_, i) => point(i, n, r * l)).map(p => `${p.x},${p.y}`).join(' ')
  )

  // Data polygon
  const dataPts = items.map((item, i) => point(i, n, r * item.score / 100))
  const dataPolygon = dataPts.map(p => `${p.x},${p.y}`).join(' ')

  // Labels
  const labels = items.map((item, i) => {
    const p = point(i, n, r + 22)
    return { x: p.x, y: p.y + 5, text: item.label }
  })

  // Dots on data
  const dots = dataPts.map(p => ({ x: p.x, y: p.y }))

  return { bgLevels, dataPolygon, labels, dots }
})

function arrowDown() {
  return null
}
</script>

<template>
  <n-card size="small" :bordered="true" style="margin-bottom: 12px;">
    <n-space justify="space-between" align="center" style="margin-bottom: 12px;">
      <n-button size="tiny" quaternary @click="showCriteria = true">
        {{ $t('radar.title') }}
      </n-button>
      <n-space size="small" align="center">
        <n-select v-if="strategyNames.length"
          :value="selectedStrategy" :options="strategyNames.map(n => ({ label: n, value: n }))"
          @update:value="(v: string) => emit('select', v)"
          style="width: 180px;" :placeholder="$t('radar.select_strategy')" />
        <n-select v-if="versionOptions.length && selectedStrategy"
          :value="selectedVersion || ''" :options="versionOptions"
          @update:value="(v: string) => emit('select-version', v)"
          style="width: 170px;" :placeholder="$t('radar.select_version')" clearable />
      </n-space>
    </n-space>

    <n-grid :cols="2" :x-gap="24">
      <!-- 六边形图 -->
      <n-gi>
        <div style="display: flex; justify-content: center;">
          <svg v-if="axes.labels.length" width="320" height="320" viewBox="0 0 320 320">
            <!-- 背景多边形 -->
            <polygon v-for="(poly, li) in axes.bgLevels" :key="li"
              :points="poly" fill="#ffffff08" stroke="#ffffff15" stroke-width="1" />
            <!-- 轴线 -->
            <line v-for="(_, i) in scores" :key="'axis'+i"
              :x1="cx" :y1="cy"
              :x2="point(i, scores.length, r).x"
              :y2="point(i, scores.length, r).y"
              stroke="#ffffff20" stroke-width="1" />
            <!-- 数据多边形 -->
            <polygon :points="axes.dataPolygon"
              fill="#f0b90b30" stroke="#f0b90b" stroke-width="2" />
            <!-- 数据点 -->
            <circle v-for="(dot, di) in axes.dots" :key="'dot'+di"
              :cx="dot.x" :cy="dot.y" r="4" fill="#f0b90b" stroke="#fff" stroke-width="1" />
            <!-- 标签 -->
            <text v-for="(lab, li) in axes.labels" :key="'lab'+li"
              :x="lab.x" :y="lab.y"
              text-anchor="middle" dominant-baseline="middle"
              fill="#aaa" font-size="12">{{ lab.text }}</text>
          </svg>
          <n-empty v-else :description="$t('radar.no_data')" />
        </div>
      </n-gi>

      <!-- 右侧分数详情 -->
      <n-gi>
        <n-space vertical size="small">
          <n-h3 style="margin: 0;">
            {{ $t('radar.composite_score') }}
            <n-tag :color="{ color: grade.color }" size="small" style="margin-left: 8px;">
              {{ grade.label }}
            </n-tag>
          </n-h3>
          <n-progress type="circle" :percentage="totalScore" :color="grade.color"
            :stroke-width="10" :size="80" style="align-self: center; margin: 8px 0;">
            {{ totalScore }}
          </n-progress>

          <n-table size="small" :bordered="false" :single-line="false" style="font-size: 13px;">
            <thead>
              <tr>
                <th>{{ $t('radar.indicator') }}</th>
                <th style="text-align:right;">{{ $t('radar.current_value') }}</th>
                <th style="text-align:right;">{{ $t('radar.score') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in scores" :key="item.label">
                <td>{{ item.label }}</td>
                <td style="text-align:right;">
                  <n-text depth="3">{{ typeof item.raw === 'number' ? item.raw.toFixed(2) : item.raw }}</n-text>
                </td>
                <td style="text-align:right;">
                  <n-text :style="{ color: item.score >= 60 ? '#0ecb81' : item.score >= 40 ? '#f0b90b' : '#f6465d' }">
                    {{ item.score }}
                  </n-text>
                </td>
              </tr>
              <tr>
                <td><strong>{{ $t('radar.total_score') }}</strong></td>
                <td></td>
                <td style="text-align:right;">
                  <strong :style="{ color: grade.color }">{{ totalScore }}</strong>
                </td>
              </tr>
            </tbody>
          </n-table>
        </n-space>
      </n-gi>
    </n-grid>
  </n-card>

  <!-- 评估标准弹窗 -->
  <n-modal v-model:show="showCriteria" preset="card" :title="$t('radar.title')" style="max-width: 520px;">
    <n-space vertical size="small">
      <n-text depth="2">{{ $t('radar.scoring_desc') }}</n-text>
      <n-table size="small" :bordered="true" :single-line="false" style="font-size: 13px;">
        <thead>
          <tr>
            <th>{{ $t('radar.indicator') }}</th>
            <th>{{ $t('radar.weight') }}</th>
            <th>{{ $t('radar.scoring_method') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>Profit Factor</td><td>25%</td><td>{{ $t('radar.method_pf') }}</td></tr>
          <tr><td>{{ $t('radar.win_rate') }}</td><td>20%</td><td>{{ $t('radar.method_winrate') }}</td></tr>
          <tr><td>{{ $t('radar.profit_ratio') }}</td><td>25%</td><td>{{ $t('radar.method_ratio') }}</td></tr>
          <tr><td>{{ $t('radar.consec_loss_ctrl') }}</td><td>15%</td><td>{{ $t('radar.method_consec') }}</td></tr>
          <tr><td>{{ $t('radar.expected_return') }}</td><td>15%</td><td>{{ $t('radar.method_ep') }}</td></tr>
        </tbody>
      </n-table>
      <n-text depth="3" style="font-size: 13px;">
        <b>{{ $t('radar.excellent') }}</b> ≥ 80 &nbsp; <b>{{ $t('radar.good') }}</b> ≥ 60 &nbsp; <b>{{ $t('radar.pass') }}</b> ≥ 40 &nbsp; <b>{{ $t('radar.fail') }}</b> &lt; 40
      </n-text>
    </n-space>
  </n-modal>
</template>
