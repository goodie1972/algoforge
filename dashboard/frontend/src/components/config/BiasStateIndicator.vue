<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { getBiasState, forceRefreshBias } from '@/api/client'

const state = ref<{
  direction: string | null
  score: number
  updated_at: number
  source: string
  age_seconds: number | null
} | null>(null)
const refreshing = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    state.value = await getBiasState()
  } catch { /* ignore */ }
}
async function refresh() {
  refreshing.value = true
  try {
    const r = await forceRefreshBias()
    state.value = r.full
  } catch { /* ignore */ }
  finally {
    refreshing.value = false
  }
}
onMounted(() => {
  load()
  timer = setInterval(load, 30000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })

const dirLabel = computed(() => {
  const d = state.value?.direction
  if (d === 'bullish') return '看涨'
  if (d === 'bearish') return '看跌'
  if (d === 'neutral') return '震荡'
  return '无数据'
})
const dirColor = computed(() => {
  const d = state.value?.direction
  if (d === 'bullish') return '#0ecb81'
  if (d === 'bearish') return '#f6465d'
  return '#888'
})
const isStale = computed(() => {
  const age = state.value?.age_seconds
  if (age == null) return true
  return age > 180
})
</script>

<template>
  <div style="display: flex; align-items: center; gap: 10px; font-size: 12px; line-height: 1.5;">
    <n-tag :bordered="false" size="small" :style="{
      background: dirColor + '20',
      color: dirColor,
      fontWeight: 700,
    }">
      <span v-if="!state">—</span>
      <span v-else>{{ dirLabel }} {{ state.score ? (state.score > 0 ? '+' : '') + state.score.toFixed(2) : '' }}</span>
    </n-tag>
    <span v-if="state?.age_seconds != null" :style="{color: isStale ? '#f6465d' : '#888', fontSize: '10px'}">
      {{ Math.round(state.age_seconds) }}s 前更新
    </span>
    <n-button size="tiny" quaternary :loading="refreshing" @click="refresh">↻</n-button>
    <n-text v-if="!state" depth="3" style="font-size: 10px;">引擎未启动或 DB 为空</n-text>
  </div>
</template>
