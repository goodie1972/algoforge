<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSignalStore } from '@/stores/signals'
import { usePriceStore } from '@/stores/prices'
import { useConfigStore } from '@/stores/config'
import { getStrategyColor, getStrategyTextColor } from '@/utils/strategyColors'

const signalStore = useSignalStore()
const priceStore = usePriceStore()
const configStore = useConfigStore()

const { t } = useI18n()

// ── News calendar ──

interface NewsEvent {
  title: string
  country: string
  impact: string
  datetime: string
  forecast: string
  previous: string
}

interface CalendarData {
  is_blackout: boolean
  blackout_reason: string
  upcoming_events: NewsEvent[]
  blackout_windows: Array<{ start: string; end: string; title: string }>
}

const calendarData = ref<CalendarData | null>(null)
const loadingNews = ref(false)
const newsExpanded = ref(false)
let refreshTimer: number | null = null
let refreshTimer2: number | null = null

async function fetchCalendar() {
  loadingNews.value = true
  try {
    const res = await fetch('/api/news/calendar')
    if (res.ok) calendarData.value = await res.json()
  } catch (e) {
    console.error('新闻日历获取失败', e)
  } finally {
    loadingNews.value = false
  }
}

const nextEvent = computed(() => calendarData.value?.upcoming_events?.[0] ?? null)

function evtName(title: string) {
  const key = `signals.news.${title}`
  const cn = t(key)
  return cn !== key ? `${cn}（${title}）` : title
}

const activeStrategies = computed(() => {
  const pool = configStore.items.strategy_pool || {}
  return Object.entries(pool)
    .filter(([, cfg]: [string, any]) => cfg.enabled !== false)
    .map(([name, cfg]: [string, any]) => ({
      name,
      magic: cfg.magic || 0,
      timeframe: cfg.timeframe || 'H1',
    }))
})

// 策略颜色统一由 getStrategyColor(name) 动态分配
// 同一基名的策略（如 mfi_bb_m30 / mfi_bb_m30_optimized）自动同色系不同深浅

interface StratSide {
  title: string; color: string; entry: string[]; exit: string[];
}

interface StratLogic {
  desc: string; long: StratSide; short: StratSide;
}

const strategyLogics = ref<Record<string, StratLogic>>({})

function renderLogic(l: any): string {
  if (typeof l === 'string') return l
  if (l.name != null) return `${l.score} ${l.name} — ${l.detail}`
  if (l.method != null) return `${l.method} — ${l.normal}`
  return String(l)
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

const expandedStratKeys = ref<string[]>([])


interface GoldNewsItem {
  id: number
  source: string
  content: string
  direction: string
  direction_confidence: string
  news_time: string
  fetched_at: number
}

interface GoldNewsData {
  summary: { total: number; bullish: number; bearish: number; neutral: number; last_fetch: number }
  current_bias: { overall: string; bullish_score: number; bearish_score: number } | null
  evaluation: { evaluated: number; correct: number; wrong: number; pending: number; accuracy: number }
  news: GoldNewsItem[]
}

const goldNews = ref<GoldNewsData | null>(null)
const goldShowAll = ref(false)
const calendarShowAll = ref(false)
const loadingGold = ref(false)

async function fetchGoldNews() {
  loadingGold.value = true
  try {
    const res = await fetch('/api/news/gold')
    if (res.ok) goldNews.value = await res.json()
  } catch { /* ignore */ }
  finally { loadingGold.value = false }
}

function goldDirColor(dir: string): string {
  return dir === 'bullish' ? '#0ecb81' : dir === 'bearish' ? '#f6465d' : '#8b8f97'
}

function goldDirLabel(dir: string): string {
  return dir === 'bullish' ? '利多' : dir === 'bearish' ? '利空' : '中性'
}

function impactColor(impact: string) {
  return impact === 'High' ? '#f6465d' : impact === 'Medium' ? '#f0a020' : '#8b8f97'
}

onMounted(() => {
  fetchGoldNews()
  configStore.fetch()
  fetchCalendar()
  fetchLogics()
  refreshTimer = window.setInterval(fetchCalendar, 300000)
  refreshTimer2 = window.setInterval(fetchGoldNews, 300000)
})

onUnmounted(() => {
  if (refreshTimer !== null) clearInterval(refreshTimer)
  if (refreshTimer2 !== null) clearInterval(refreshTimer2)
})
</script>

<template>
  <n-space vertical size="small">

    
<!-- ═══════════════ 实盘信号 ═══════════════ -->
    <n-card size="small" :bordered="true"
      :style="{
        borderLeft: `4px solid ${
          signalStore.signal === 'BUY' ? '#0ecb81'
          : signalStore.signal === 'SELL' ? '#f6465d'
          : '#8b8f97'
        }`,
      }">
      <n-space vertical>
        <!-- 信号指示：仅在有信号时显示 -->
        <div v-if="signalStore.signal" style="text-align: center; padding: 4px 0 8px;">
          <n-h2 style="margin: 0;" prefix="bar">
            <n-text
              :type="signalStore.signal === 'BUY' ? 'success' : 'error'"
              style="font-size: 28px; font-weight: 700; letter-spacing: 2px;">
              <span v-if="signalStore.signal === 'BUY'" style="color: #0ecb81;">▲ BUY</span>
              <span v-else style="color: #f6465d;">▼ SELL</span>
            </n-text>
          </n-h2>
          <n-text v-if="signalStore.timestamp" depth="3" style="font-size: 12px;">
            {{ signalStore.timestamp }}
          </n-text>
        </div>

        <!-- 报价：一行显示，统一格式 -->
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 0;">
          <span style="font-size: 15px; font-weight: 600;">{{ $t('signals.current_price') }} <span style="color:#f0b90b;">{{ priceStore.midPrice.toFixed(2) }}</span></span>
          <span style="font-size: 15px; font-weight: 600;">Bid <span style="color:#0ecb81;">{{ priceStore.bid.toFixed(2) }}</span> / Ask <span style="color:#f6465d;">{{ priceStore.ask.toFixed(2) }}</span></span>
          <span style="font-size: 15px; font-weight: 600;">{{ $t('signals.spread') }} <span style="color:#8b8f97;">{{ priceStore.spread.toFixed(2) }}</span></span>
        </div>
      </n-space>
    </n-card>

    

    
    <!-- ═══════════════ 黄金快讯评估 ═══════════════ -->
    <n-card title="黄金快讯" size="small" :bordered="true"
      :style="{ borderLeft: `4px solid ${goldNews?.current_bias?.overall === 'BULLISH' ? '#0ecb81' : goldNews?.current_bias?.overall === 'BEARISH' ? '#f6465d' : '#8b8f97'}` }">
      <template #header-extra>
        <div style="display:flex;align-items:center;gap:8px">
          <n-tag v-if="goldNews?.current_bias" size="tiny" :bordered="false"
            :type="goldNews.current_bias.overall === 'BULLISH' ? 'success' : goldNews.current_bias.overall === 'BEARISH' ? 'error' : 'default'">
            {{ goldNews.current_bias.overall === 'BULLISH' ? '看多' : goldNews.current_bias.overall === 'BEARISH' ? '看空' : '中性' }}
          </n-tag>
          <n-button size="tiny" text style="font-size:22px;font-weight:700;color:#8b8f97;cursor:pointer" @click="goldShowAll = true">⤢</n-button>
        </div>
      </template>

            <n-space vertical size="small">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <n-text depth="3" style="font-size:12px">
            {{ goldNews?.summary?.bullish ?? 0 }}利多 / {{ goldNews?.summary?.bearish ?? 0 }}利空 / {{ goldNews?.summary?.neutral ?? 0 }}中性
          </n-text>
          <n-text v-if="goldNews?.evaluation" depth="3" style="font-size:12px">
            准确率 {{ goldNews.evaluation.accuracy }}%
          </n-text>
        </div>

        <!-- 最近快讯列表（前4条） -->
        <div v-for="item in goldNews?.news?.slice(0, 5)" :key="item.id"
          style="padding:4px 8px;border-radius:4px;background:var(--n-color-embedded)">
          <div style="display:flex;align-items:flex-start;gap:6px">
            <n-tag size="tiny" :bordered="false" style="margin-top:2px;flex-shrink:0"
              :type="item.direction === 'bullish' ? 'success' : item.direction === 'bearish' ? 'error' : 'default'">
              {{ item.direction === 'bullish' ? '多' : item.direction === 'bearish' ? '空' : '-' }}
            </n-tag>
            <n-text style="font-size:12px;line-height:1.4">{{ item.content.slice(0, 60) }}{{ item.content.length > 60 ? '...' : '' }}</n-text>
          </div>
          <div style="display:flex;justify-content:space-between;margin-top:2px">
            <n-text depth="3" style="font-size:11px">{{ item.source === 'huicong' ? '汇通' : '金十' }}</n-text>
            <n-text depth="3" style="font-size:11px">{{ item.news_time }}</n-text>
          </div>
        </div>
        <div v-if="loadingGold" style="text-align:center;padding:8px">
          <n-spin size="small" />
        </div>
      </n-space>
    </n-card>

    

    <!-- 黄金快讯完整窗口（居中悬浮） -->
    <n-modal v-model:show="goldShowAll" :mask-closable="true" preset="card" :title="'黄金快讯完整列表'" style="width:75vw;max-height:75vh;overflow-y:auto">
      <div style="display:flex;align-items:center;gap:10px;padding:8px 0">
        <n-tag v-if="goldNews?.current_bias" :bordered="false"
          :type="goldNews.current_bias.overall === 'BULLISH' ? 'success' : goldNews.current_bias.overall === 'BEARISH' ? 'error' : 'default'">
          {{ goldNews.current_bias.overall === 'BULLISH' ? '看多' : goldNews.current_bias.overall === 'BEARISH' ? '看空' : '中性' }}
        </n-tag>
        <n-text depth="3" style="font-size:18px">
          {{ goldNews?.summary?.bullish ?? 0 }}利多 / {{ goldNews?.summary?.bearish ?? 0 }}利空 / {{ goldNews?.summary?.neutral ?? 0 }}中性
        </n-text>
      </div>
      <n-divider style="margin:4px 0" />
      <div style="max-height:calc(75vh - 120px);overflow-y:auto">
        <n-space vertical size="small">
          <div v-for="item in goldNews?.news" :key="item.id"
            style="padding:8px;border-radius:6px;background:var(--n-color-embedded)">
            <div style="display:flex;align-items:flex-start;gap:6px">
              <n-tag size="tiny" :bordered="false" style="margin-top:2px;flex-shrink:0"
                :type="item.direction === 'bullish' ? 'success' : item.direction === 'bearish' ? 'error' : 'default'">
                {{ item.direction === 'bullish' ? '利多' : item.direction === 'bearish' ? '利空' : '中性' }}
              </n-tag>
              <n-text style="font-size:18px;line-height:1.6">{{ item.content }}</n-text>
            </div>
            <div style="display:flex;justify-content:space-between;margin-top:4px">
              <n-text depth="3" style="font-size:16px">{{ item.source === 'huicong' ? '汇通' : '金十' }}</n-text>
              <n-text depth="3" style="font-size:16px">{{ item.news_time || '' }}</n-text>
            </div>
          </div>
          <div v-if="!goldNews?.news?.length" style="text-align:center;padding:30px 0;color:#8b8f97">暂无快讯</div>
        </n-space>
      </div>
    </n-modal>



    <!-- ═══════════════ 实盘策略 ═══════════════ -->
    <n-card size="small" :bordered="true">
      <n-collapse :expanded-names="expandedStratKeys" @update:expanded-names="expandedStratKeys = $event">
        <n-collapse-item v-for="s in activeStrategies" :key="s.name" :name="s.name"
          :style="{ borderLeft: `3px solid ${getStrategyColor(s.name)}`,
                   marginBottom: '4px', borderRadius: '4px' }">
          <template #header>
            <n-space align="center" size="small">
              <n-tag :color="{ color: getStrategyColor(s.name), textColor: getStrategyTextColor(s.name) }" size="tiny" style="font-weight: 600; font-size: 14px; padding: 2px 7px;">
                {{ s.name }}
              </n-tag>
              <n-text depth="3" style="font-size: 11px;">TF:{{ s.timeframe }}</n-text>
              <n-text depth="3" style="font-size: 11px;">M:{{ s.magic }}</n-text>
            </n-space>
          </template>
          <n-text depth="2" style="font-size: 12px; display: block; margin-bottom: 6px;">
            {{ strategyLogics[s.name]?.desc || '' }}
          </n-text>
          <template v-if="strategyLogics[s.name]">
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 4px;">
              <!-- 做空 -->
              <div style="background: #1a1a2e; border-radius: 4px; padding: 6px 8px; border-left: 3px solid #f6465d;">
                <div style="font-weight:700; color:#f6465d; font-size:12px; margin-bottom:4px;">{{ $t('signals.short_label') }}</div>
                <div style="font-size:10px; color:#8b8f97; margin-bottom:2px;">{{ $t('signals.entry') }}:</div>
                <div v-for="(l, li) in strategyLogics[s.name]!.short.entry" :key="'se'+li"
                  style="font-size:10px; color:#ccc; padding:1px 0;">{{ renderLogic(l) }}</div>
                <div style="font-size:10px; color:#8b8f97; margin:4px 0 2px;">{{ $t('signals.exit') }}:</div>
                <div v-for="(l, li) in strategyLogics[s.name]!.short.exit" :key="'sx'+li"
                  style="font-size:10px; color:#999; padding:1px 0;">{{ renderLogic(l) }}</div>
              </div>
              <!-- 做多 -->
              <div style="background: #1a1a2e; border-radius: 4px; padding: 6px 8px; border-left: 3px solid #0ecb81;">
                <div style="font-weight:700; color:#0ecb81; font-size:12px; margin-bottom:4px;">{{ $t('signals.long_label') }}</div>
                <div style="font-size:10px; color:#8b8f97; margin-bottom:2px;">{{ $t('signals.entry') }}:</div>
                <div v-for="(l, li) in strategyLogics[s.name]!.long.entry" :key="'le'+li"
                  style="font-size:10px; color:#ccc; padding:1px 0;">{{ renderLogic(l) }}</div>
                <div style="font-size:10px; color:#8b8f97; margin:4px 0 2px;">{{ $t('signals.exit') }}:</div>
                <div v-for="(l, li) in strategyLogics[s.name]!.long.exit" :key="'lx'+li"
                  style="font-size:10px; color:#999; padding:1px 0;">{{ renderLogic(l) }}</div>
              </div>
            </div>
          </template>
          <div v-else style="font-size:11px; color:#8b8f97; padding:4px 0;">{{ $t('signals.no_detail') }}</div>
        </n-collapse-item>
        <n-empty v-if="!activeStrategies.length" :description="$t('signals.no_running')" />
      </n-collapse>
    </n-card>
  </n-space>
</template>
