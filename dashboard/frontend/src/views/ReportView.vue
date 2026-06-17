<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, h } from 'vue'
import {
  NCard, NSpace, NSpin, NEmpty, NAlert, NButton, NDatePicker, NTag,
  NGrid, NGi, NStatistic, NDataTable,
  NTabs, NTabPane, NThing
} from 'naive-ui'
import {
  getReports, getReportById, getReportTimeline, generateReport,
  getNewsBiasReports, getNewsBiasReport, getLatestNewsBias, generateNewsBiasReport,
  getPrice,
} from '@/api/client'

const loading = ref(false)
const error = ref('')
const activeTab = ref('daily')
const selectedDate = ref<number>(Date.now())
const timelineItems = ref<any[]>([])
const currentReport = ref<any>(null)
const generating = ref(false)

// News-bias 独立数据
const newsBiasTimeline = ref<any[]>([])
const newsBiasReport = ref<any>(null)
const livePrice = ref<{ bid: number; ask: number; spread: number } | null>(null)
let priceTimer: ReturnType<typeof setInterval> | null = null

function fmtDate(ts: number): string {
  return new Date(ts).toISOString().slice(0, 10)
}

function fmtTime(dt: string): string {
  if (!dt) return ''
  return dt.slice(11, 16)
}

function fmtTimeFull(dt: string): string {
  if (!dt) return ''
  return dt.slice(0, 19).replace('T', ' ')
}

async function loadTimeline() {
  if (activeTab.value === 'news_bias') {
    const date = fmtDate(selectedDate.value)
    try {
      const res = await getNewsBiasReports({ date })
      newsBiasTimeline.value = res.data || []
    } catch {
      newsBiasTimeline.value = []
    }
    return
  }
  const date = fmtDate(selectedDate.value)
  try {
    const res = await getReportTimeline(date, activeTab.value)
    timelineItems.value = res.data || []
  } catch {
    timelineItems.value = []
  }
}

async function loadReport(id: number) {
  if (activeTab.value === 'news_bias') {
    loading.value = true
    error.value = ''
    try {
      newsBiasReport.value = await getNewsBiasReport(id)
    } catch (e: any) {
      error.value = e?.message || '加载失败'
      newsBiasReport.value = null
    }
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    currentReport.value = await getReportById(id)
  } catch (e: any) {
    error.value = e?.message || '加载失败'
    currentReport.value = null
  }
  loading.value = false
}

function selectTimeline(item: any) {
  if (item.id) loadReport(item.id)
}

function selectNewsBiasTimeline(item: any) {
  if (item.id) loadReport(item.id)
}

async function autoLoadFirst() {
  await loadTimeline()
  if (activeTab.value === 'news_bias') {
    if (newsBiasTimeline.value.length > 0) {
      await loadReport(newsBiasTimeline.value[0].id)
    } else {
      newsBiasReport.value = null
    }
    return
  }
  if (timelineItems.value.length > 0) {
    await loadReport(timelineItems.value[0].id)
  } else {
    currentReport.value = null
  }
}

async function handleGenerate() {
  generating.value = true
  try {
    if (activeTab.value === 'news_bias') {
      await generateNewsBiasReport()
      await autoLoadFirst()
    } else {
      const date = activeTab.value === 'weekly' ? fmtDate(selectedDate.value) : ''
      await generateReport(activeTab.value, date)
      await autoLoadFirst()
    }
  } catch (e: any) {
    error.value = e?.message || '生成失败'
  }
  generating.value = false
}

watch([activeTab, selectedDate], async () => {
  currentReport.value = null
  newsBiasReport.value = null
  await autoLoadFirst()
})

onMounted(async () => {
  await autoLoadFirst()
})

// 实时价格轮询（新闻评估 tab）
onUnmounted(() => {
  if (priceTimer) clearInterval(priceTimer)
})

async function refreshPrice() {
  try {
    livePrice.value = await getPrice()
  } catch { /* ignore */ }
}

watch(activeTab, (tab) => {
  if (tab === 'news_bias') {
    refreshPrice()
    priceTimer = setInterval(refreshPrice, 5000)
  } else if (priceTimer) {
    clearInterval(priceTimer)
    priceTimer = null
  }
})

// 安全解析 content
const sections = computed(() => {
  const r = currentReport.value
  if (!r) return []
  let content = r.content
  if (typeof content === 'string') {
    try { content = JSON.parse(content) } catch { return [] }
  }
  return content?.sections || []
})

// 安全获取数值
function getNum(obj: any, key: string, fallback = 0): number {
  return obj?.[key] ?? fallback
}

function fmtPnl(v: number): string {
  return `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`
}

function fmtPnlColor(v: number): string {
  return v >= 0 ? '#0ecb81' : '#f6465d'
}

// ── News-bias 辅助函数 ────────────────────────────────
function nbTagType(dir: string): 'success' | 'error' | 'warning' | 'default' {
  if (dir === 'bullish') return 'success'
  if (dir === 'bearish') return 'error'
  return 'warning'
}

function nbDirectionLabel(dir: string): string {
  if (dir === 'bullish') return '看涨 ↑'
  if (dir === 'bearish') return '看跌 ↓'
  return '震荡 →'
}

const VAR_LABELS: Record<string, string> = {
  inflation: '通胀',
  rates: '利率政策',
  geopolitical: '地缘政治',
  usd: '美元/收益率',
  cb_buying: '央行购金',
}

function nbVarLabel(v: string): string {
  return VAR_LABELS[v] || v
}

function nbVarTagType(v: string): 'info' | 'error' | 'warning' | 'success' | 'default' {
  const map: Record<string, 'info' | 'error' | 'warning' | 'success' | 'default'> = {
    inflation: 'error',
    rates: 'warning',
    geopolitical: 'info',
    usd: 'info',
    cb_buying: 'success',
  }
  return map[v] || 'default'
}

function nbRsiColor(rsi: number): string {
  if (rsi >= 70) return '#f6465d'
  if (rsi <= 30) return '#0ecb81'
  return '#f0b90b'
}

// 变量评分（横向条）：左侧利多占比 / 右侧利空占比 / 中心得分标记
function nbVarBarWidth(score: number, side: 'bull' | 'bear' | 'mid'): number {
  // score 范围 -1..+1，转为百分比宽度
  const abs = Math.abs(score) * 50  // 满格 50%
  if (side === 'bull') return score > 0 ? abs : 0
  if (side === 'bear') return score < 0 ? abs : 0
  return 0  // mid 不占宽度
}

function nbVarPct(v: number | undefined): string {
  if (v == null) return '0.0'
  return v.toFixed(1)
}

function nbVarArrow(score: number): string {
  if (score > 0.3) return '↑ 偏多'
  if (score < -0.3) return '↓ 偏空'
  if (score > 0) return '↗ 偏多'
  if (score < 0) return '↘ 偏空'
  return '→ 中性'
}

function nbDirColor(d: string): string {
  if (d === 'bullish') return '#0ecb81'
  if (d === 'bearish') return '#f6465d'
  return '#f0b90b'
}

function nbDirBg(d: string): string {
  if (d === 'bullish') return 'rgba(14, 203, 129, 0.12)'
  if (d === 'bearish') return 'rgba(246, 70, 93, 0.12)'
  return 'rgba(240, 185, 11, 0.10)'
}

function nbDirIcon(d: string): string {
  if (d === 'bullish') return '▲'
  if (d === 'bearish') return '▼'
  return '◆'
}

function nbBuildSummary(r: any): string {
  // 一句话总结：从预判和关键变量拼
  if (!r) return ''
  const p = r.prediction || {}
  const dirLabel = nbDirectionLabel(p.direction)
  const vs = r.variable_scores || {}
  const infl = vs.inflation?.score || 0
  const geo = vs.geopolitical?.score || 0
  const parts: string[] = []
  if (Math.abs(infl) > 0.3) parts.push(`通胀${nbVarArrow(infl)}`)
  if (Math.abs(geo) > 0.3) parts.push(`地缘${nbVarArrow(geo)}`)
  return `${dirLabel} · ${parts.join(' · ') || '变量不显著'}`
}
</script>

<template>
  <div style="display: flex; height: calc(100vh - 100px); gap: 16px;">
    <!-- 左侧面板 -->
    <div style="width: 300px; min-width: 300px; display: flex; flex-direction: column; gap: 12px; overflow-y: auto;">
      <n-date-picker v-model:value="selectedDate" type="date" clearable
        style="width: 100%;" />

      <n-tabs v-model:value="activeTab" type="line" size="small" animated>
        <n-tab-pane name="daily" tab="日报" />
        <n-tab-pane name="weekly" tab="周报" />
        <n-tab-pane name="news_bias" tab="新闻评估" />
      </n-tabs>

      <!-- 时间轴 -->
      <div style="flex: 1; overflow-y: auto;">
        <!-- 新闻评估时间轴 -->
        <template v-if="activeTab === 'news_bias'">
          <div v-if="newsBiasTimeline.length === 0 && !loading" style="padding: 16px;">
            <n-empty description="当日无新闻预判">
              <template #extra>
                <n-button size="small" secondary :loading="generating" @click="handleGenerate">
                  手动生成
                </n-button>
              </template>
            </n-empty>
          </div>
          <n-thing v-for="item in newsBiasTimeline" :key="item.id"
            :style="{
              padding: '6px 10px',
              marginBottom: '4px',
              cursor: 'pointer',
              background: newsBiasReport?.id === item.id ? 'rgba(240, 185, 11, 0.12)' : 'transparent',
              borderRadius: '4px',
              borderLeft: newsBiasReport?.id === item.id ? '3px solid #f0b90b' : '3px solid transparent',
            }"
            @click="selectNewsBiasTimeline(item)">
            <template #header>
              <div style="display: flex; align-items: center; gap: 6px;">
                <span :style="{
                  display: 'inline-block', width: '24px', textAlign: 'center',
                  fontSize: '12px', fontWeight: 700,
                  color: (() => {
                    try { const p = typeof item.prediction === 'string' ? JSON.parse(item.prediction) : item.prediction; return nbDirColor(p?.direction || 'sideways'); }
                    catch { return '#888'; }
                  })(),
                }">
                  {{ (() => {
                    try { const p = typeof item.prediction === 'string' ? JSON.parse(item.prediction) : item.prediction; return nbDirIcon(p?.direction || 'sideways'); }
                    catch { return '◆'; }
                  })() }}
                </span>
                <n-tag type="warning" size="tiny" :bordered="false" style="font-family: monospace;">
                  {{ item.created_at?.slice(11, 16) || '' }}
                </n-tag>
                <n-tag v-if="item.verify_result" size="tiny"
                  :type="item.verify_result === 'correct' ? 'success' : 'error'" :bordered="false">
                  {{ item.verify_result === 'correct' ? '✓' : '✗' }}
                </n-tag>
              </div>
            </template>
            <template #description>
              <div style="font-size: 11px; color: #aaa; line-height: 1.4; margin-top: 2px;">
                {{ (() => {
                  try {
                    const p = typeof item.prediction === 'string' ? JSON.parse(item.prediction) : item.prediction
                    const dir = nbDirectionLabel(p?.direction || 'sideways')
                    const score = (p?.score ?? 0).toFixed(2)
                    const conf = p?.confidence ?? 0
                    return `${dir} · 评分 ${score > 0 ? '+' : ''}${score} · 置信 ${conf}%`
                  } catch {
                    return item.summary || '—'
                  }
                })() }}
              </div>
            </template>
          </n-thing>
        </template>

        <!-- 日报/周报时间轴 -->
        <template v-else>
          <div v-if="timelineItems.length === 0 && !loading" style="padding: 16px;">
            <n-empty description="当日无报告">
              <template #extra>
                <n-button size="small" secondary :loading="generating" @click="handleGenerate">
                  手动生成
                </n-button>
              </template>
            </n-empty>
          </div>
          <n-thing v-for="item in timelineItems" :key="item.id"
            :style="{
              padding: '4px 8px',
              cursor: 'pointer',
              background: currentReport?.id === item.id ? '#1a1a2e' : 'transparent',
              borderRadius: '4px',
              fontWeight: currentReport?.id === item.id ? 700 : 400,
            }"
            @click="selectTimeline(item)">
            <template #header>
              <div style="display: flex; align-items: center; gap: 6px;">
                <n-tag :type="activeTab === 'daily' ? 'info' : 'success'"
                  size="tiny" :bordered="false">
                  {{ activeTab === 'daily' ? fmtTime(item.created_at) : item.created_at?.slice(0, 10) }}
                </n-tag>
                <n-tag v-if="item.floating_pnl < -10"
                  size="tiny" type="error" :bordered="false">浮亏</n-tag>
              </div>
            </template>
            <template #description>
              <div style="font-size: 12px; color: #888; line-height: 1.4;">
                <div>余额 ${{ (item.account_balance ?? 0).toFixed(2) }}</div>
                <div>
                  持仓 {{ item.position_count ?? 0 }} 单
                  <span :style="{ color: fmtPnlColor(item.daily_pnl) }">
                    {{ fmtPnl(item.daily_pnl) }}
                  </span>
                </div>
              </div>
            </template>
          </n-thing>
        </template>
      </div>
    </div>

    <!-- 右侧内容区 -->
    <div style="flex: 1; overflow-y: auto; padding-left: 8px;">

      <!-- ══════════════════════════════════════════════════
           新闻评估 tab
           ══════════════════════════════════════════════════ -->
      <div v-if="activeTab === 'news_bias'">
        <!-- 加载态 -->
        <div v-if="loading" style="display: flex; justify-content: center; padding: 80px 0;">
          <n-spin size="large" />
        </div>

        <!-- 错误态 -->
        <n-alert v-else-if="error" type="error" :title="error" closable style="margin-bottom: 16px;" />

        <!-- 空态 -->
        <n-empty v-else-if="!newsBiasReport" description="选择左侧报告查看详情">
          <template #extra>
            <n-button size="small" secondary :loading="generating" @click="handleGenerate">
              生成报告
            </n-button>
          </template>
        </n-empty>

        <!-- 数据态 -->
        <template v-else>
          <!-- 标题 + 一句话总结 -->
          <div style="margin-bottom: 16px; padding: 12px 16px; background: #1a1d23; border-radius: 6px; border-left: 3px solid #f0b90b;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span style="font-size: 17px; font-weight: 700;">{{ newsBiasReport.title }}</span>
              <n-tag size="small" type="warning" :bordered="false">新闻预判</n-tag>
              <n-tag v-if="newsBiasReport.verify_result" size="small"
                :type="newsBiasReport.verify_result === 'correct' ? 'success' : 'error'" :bordered="false">
                {{ newsBiasReport.verify_result === 'correct' ? '✓ 验证正确' : '✗ 验证错误' }}
              </n-tag>
            </div>
            <div style="margin-top: 6px; font-size: 13px; color: #aaa; line-height: 1.5;">
              {{ nbBuildSummary(newsBiasReport) }}
            </div>
            <div style="margin-top: 4px; font-size: 11px; color: #666;">
              生成时间：{{ newsBiasReport.created_at }}
            </div>
          </div>

          <!-- ① 预判结论 — 突出方向 + 关键数据 -->
          <n-card size="small" bordered style="margin-bottom: 12px;"
            :content-style="{ padding: '14px 18px' }">
            <template #header>
              <span style="font-weight: 600;">① 预判结论（未来 12 小时）</span>
            </template>
            <div style="display: flex; align-items: stretch; gap: 10px;">
              <!-- 方向大字 -->
              <div :style="{
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                background: nbDirBg(newsBiasReport.prediction?.direction),
                borderRadius: '8px', padding: '8px 10px', minWidth: '78px', flexShrink: 0,
                border: '1px solid ' + nbDirColor(newsBiasReport.prediction?.direction) + '40',
              }">
                <div style="font-size: 10px; color: #888;">方向</div>
                <div :style="{
                  fontSize: '16px', fontWeight: 800, color: nbDirColor(newsBiasReport.prediction?.direction),
                  marginTop: '2px', whiteSpace: 'nowrap',
                }">
                  {{ nbDirIcon(newsBiasReport.prediction?.direction) }} {{ nbDirectionLabel(newsBiasReport.prediction?.direction) }}
                </div>
              </div>
              <!-- 关键指标 -->
              <div style="flex: 1; display: grid; grid-template-columns: 1.1fr 0.9fr 1.1fr 1.3fr; gap: 0; minWidth: 0;">
                <div style="padding: 0 6px; border-right: 1px solid #2a2a2a; minWidth: 0;">
                  <div style="font-size: 10px; color: #888; white-space: nowrap;">综合评分</div>
                  <div :style="{
                    fontSize: '17px', fontWeight: 700, marginTop: '4px',
                    color: (newsBiasReport.prediction?.score ?? 0) > 0 ? '#0ecb81' : (newsBiasReport.prediction?.score ?? 0) < 0 ? '#f6465d' : '#aaa',
                    whiteSpace: 'nowrap', fontFamily: 'monospace',
                  }">
                    {{ (newsBiasReport.prediction?.score ?? 0) > 0 ? '+' : '' }}{{ (newsBiasReport.prediction?.score ?? 0).toFixed(2) }}
                  </div>
                </div>
                <div style="padding: 0 6px; border-right: 1px solid #2a2a2a; minWidth: 0;">
                  <div style="font-size: 10px; color: #888; white-space: nowrap;">置信度</div>
                  <div style="font-size: 17px; font-weight: 700; margin-top: 4px; white-space: nowrap; font-family: monospace;">
                    {{ newsBiasReport.prediction?.confidence ?? 0 }}<span style="font-size: 11px; color: #888;">%</span>
                  </div>
                </div>
                <div style="padding: 0 6px; border-right: 1px solid #2a2a2a; minWidth: 0;">
                  <div style="font-size: 10px; color: #888; white-space: nowrap;">技术调整</div>
                  <div :style="{
                    fontSize: '17px', fontWeight: 700, marginTop: '4px',
                    color: (newsBiasReport.prediction?.tech_adjustment ?? 0) >= 0 ? '#0ecb81' : '#f6465d',
                    whiteSpace: 'nowrap', fontFamily: 'monospace',
                  }">
                    {{ (newsBiasReport.prediction?.tech_adjustment ?? 0) > 0 ? '+' : '' }}{{ (newsBiasReport.prediction?.tech_adjustment ?? 0).toFixed(2) }}
                  </div>
                </div>
                <div style="padding: 0 6px; minWidth: 0;">
                  <div style="font-size: 10px; color: #888; white-space: nowrap;">入场价</div>
                  <div style="font-size: 17px; font-weight: 700; margin-top: 4px; white-space: nowrap; font-family: monospace;">
                    {{ newsBiasReport.entry_price?.toFixed(2) ?? '-' }}
                  </div>
                </div>
              </div>
            </div>
            <!-- 理由（分两行） -->
            <div style="margin-top: 14px; padding-top: 12px; border-top: 1px dashed #2a2a2a; font-size: 12px; line-height: 1.7;">
              <div v-if="newsBiasReport.prediction?.reason?.includes('|')">
                <div style="color: #888; margin-bottom: 4px;">
                  <span style="color: #f0b90b;">▍</span>
                  <span style="font-weight: 600;">变量得分：</span>
                  <span style="color: #ccc;">{{ newsBiasReport.prediction.reason.split('|')[0].replace('变量得分:', '').trim() }}</span>
                </div>
                <div style="color: #888;">
                  <span style="color: #f0b90b;">▍</span>
                  <span style="font-weight: 600;">技术调整：</span>
                  <span style="color: #ccc;">{{ newsBiasReport.prediction.reason.split('|').slice(1).join('|').trim() }}</span>
                </div>
              </div>
              <div v-else style="color: #ccc;">{{ newsBiasReport.prediction?.reason }}</div>
            </div>
          </n-card>

          <!-- ② 五大变量评分 — 横向条形图 -->
          <n-card size="small" bordered style="margin-bottom: 12px;">
            <template #header>
              <span style="font-weight: 600;">② 五大变量评分</span>
            </template>
            <template #header-extra>
              <span style="font-size: 11px; color: #666;">绿色=利多 ｜ 红色=利空 ｜ 中线=0</span>
            </template>
            <div style="padding: 4px 0;">
              <div v-for="(s, varName) in newsBiasReport.variable_scores" :key="String(varName)"
                style="display: flex; align-items: center; gap: 12px; margin-bottom: 14px;">
                <!-- 变量名 -->
                <div style="width: 80px; flex-shrink: 0;">
                  <div style="font-size: 13px; font-weight: 600;">{{ nbVarLabel(String(varName)) }}</div>
                  <div style="font-size: 10px; color: #666;">权重 {{ (s.weight * 100).toFixed(0) }}%</div>
                </div>
                <!-- 横向条：左红右绿 -->
                <div style="flex: 1; position: relative; height: 24px; display: flex; background: #1a1d23; border-radius: 4px; overflow: hidden;">
                  <!-- 中线 -->
                  <div style="position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: #444; z-index: 2;"></div>
                  <!-- 利多 (绿色, 在右半) -->
                  <div v-if="s.score > 0" :style="{
                    position: 'absolute', left: '50%', top: 0, bottom: 0,
                    width: nbVarBarWidth(s.score, 'bull') + '%',
                    background: 'linear-gradient(90deg, #0ecb81 0%, #0ecb81 100%)',
                    transition: 'width 0.3s',
                  }"></div>
                  <!-- 利空 (红色, 在左半) -->
                  <div v-if="s.score < 0" :style="{
                    position: 'absolute', right: '50%', top: 0, bottom: 0,
                    width: nbVarBarWidth(s.score, 'bear') + '%',
                    background: 'linear-gradient(90deg, #f6465d 0%, #f6465d 100%)',
                    transition: 'width 0.3s',
                  }"></div>
                  <!-- 得分数字（中央） -->
                  <div :style="{
                    position: 'absolute', left: 0, right: 0, top: 0, bottom: 0,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '12px', fontWeight: 700,
                    color: s.score > 0 ? '#0ecb81' : s.score < 0 ? '#f6465d' : '#888',
                    zIndex: 3,
                  }">
                    {{ s.score > 0 ? '+' : '' }}{{ s.score.toFixed(2) }}
                  </div>
                </div>
                <!-- 数字明细 -->
                <div style="width: 140px; flex-shrink: 0; font-size: 11px; color: #888; text-align: right;">
                  <span style="color: #0ecb81;">▲ {{ nbVarPct(s.bullish) }}</span>
                  <span style="margin: 0 4px; color: #555;">|</span>
                  <span style="color: #f6465d;">▼ {{ nbVarPct(s.bearish) }}</span>
                  <div style="font-size: 10px; color: #555; margin-top: 2px;">共 {{ s.count }} 条</div>
                </div>
              </div>
            </div>
          </n-card>

          <!-- ③ 关键新闻 — 分类卡片 -->
          <n-card size="small" bordered style="margin-bottom: 12px;">
            <template #header>
              <span style="font-weight: 600;">③ 关键新闻分析</span>
            </template>
            <template #header-extra>
              <span style="font-size: 11px; color: #666;">按变量分组，每组前 2 条</span>
            </template>
            <template v-if="newsBiasReport.news_items?.length">
              <!-- 按变量分组 -->
              <div v-for="(group, varName) in (
                (() => {
                  const g: Record<string, any[]> = {}
                  ;(newsBiasReport.news_items || []).forEach((n: any) => {
                    const k = n.variable || 'other'
                    if (!g[k]) g[k] = []
                    g[k].push(n)
                  })
                  return g
                })()
              )" :key="varName" style="margin-bottom: 14px;">
                <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px; padding-bottom: 4px; border-bottom: 1px solid #2a2a2a;">
                  <n-tag size="small" :type="nbVarTagType(varName)" :bordered="false" style="font-weight: 600;">
                    {{ nbVarLabel(varName) }}
                  </n-tag>
                  <span style="font-size: 11px; color: #666;">{{ group.length }} 条</span>
                </div>
                <div v-for="(item, idx) in group.slice(0, 2)" :key="idx" :style="{
                  padding: '8px 10px', marginBottom: '6px', borderRadius: '4px',
                  background: nbDirBg(item.direction),
                  borderLeft: '3px solid ' + nbDirColor(item.direction),
                }">
                  <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: wrap;">
                    <n-tag size="tiny" type="info" :bordered="false">{{ item.source }}</n-tag>
                    <n-tag size="tiny" :type="item.direction === 'bullish' ? 'success' : item.direction === 'bearish' ? 'error' : 'default'" :bordered="false">
                      {{ item.direction === 'bullish' ? '利多' : item.direction === 'bearish' ? '利空' : '中性' }}
                    </n-tag>
                    <n-tag v-if="item.weight === 'high'" size="tiny" type="warning" :bordered="false">高权重</n-tag>
                    <span style="font-size: 10px; color: #666; margin-left: auto;">{{ item.pub_date?.slice(5, 16) || '' }}</span>
                  </div>
                  <div style="font-size: 13px; line-height: 1.5; color: #ddd; word-break: break-word;">
                    {{ item.title }}
                  </div>
                  <div v-if="item.chain" :style="{
                    marginTop: '6px', padding: '4px 8px',
                    fontSize: '11px', color: '#aaa', lineHeight: 1.5,
                    background: 'rgba(255,255,255,0.04)', borderRadius: '3px',
                    fontStyle: 'italic',
                  }">
                    <span style="color: #f0b90b;">逻辑链：</span>{{ item.chain }}
                  </div>
                </div>
              </div>
            </template>
            <n-empty v-else description="无新闻数据" />
          </n-card>

          <!-- ④ 技术面快照 -->
          <n-card size="small" bordered style="margin-bottom: 12px;">
            <template #header>
              <span style="font-weight: 600;">④ 技术面快照（H1）</span>
            </template>
            <div style="display: grid; grid-template-columns: 1.3fr 0.9fr 0.9fr 1fr 1.3fr; gap: 0;">
              <div style="padding: 0 8px; border-right: 1px solid #2a2a2a; min-width: 0;">
                <div style="font-size: 10px; color: #888; white-space: nowrap;">入场价</div>
                <div style="font-size: 17px; font-weight: 700; margin-top: 4px; white-space: nowrap; font-family: monospace;">
                  {{ newsBiasReport.entry_price?.toFixed(2) ?? '-' }}
                </div>
              </div>
              <div style="padding: 0 8px; border-right: 1px solid #2a2a2a; min-width: 0;">
                <div style="font-size: 10px; color: #888; white-space: nowrap;">RSI(14)</div>
                <div :style="{
                  fontSize: '17px', fontWeight: 700, marginTop: '4px',
                  color: nbRsiColor(newsBiasReport.market_context?.rsi),
                  whiteSpace: 'nowrap', fontFamily: 'monospace',
                }">
                  {{ newsBiasReport.market_context?.rsi ?? '-' }}
                </div>
              </div>
              <div style="padding: 0 8px; border-right: 1px solid #2a2a2a; min-width: 0;">
                <div style="font-size: 10px; color: #888; white-space: nowrap;">趋势</div>
                <div style="margin-top: 6px;">
                  <n-tag size="small" :type="newsBiasReport.market_context?.trend === 'uptrend' ? 'success' : newsBiasReport.market_context?.trend === 'downtrend' ? 'error' : 'default'" :bordered="false">
                    {{ newsBiasReport.market_context?.trend === 'uptrend' ? '↑ 上升' : newsBiasReport.market_context?.trend === 'downtrend' ? '↓ 下降' : '→ 中性' }}
                  </n-tag>
                </div>
              </div>
              <div style="padding: 0 8px; border-right: 1px solid #2a2a2a; min-width: 0;">
                <div style="font-size: 10px; color: #888; white-space: nowrap;">BB 位置</div>
                <div :style="{
                  fontSize: '17px', fontWeight: 700, marginTop: '4px',
                  color: (newsBiasReport.market_context?.bb_position ?? 0.5) > 0.8 ? '#f6465d' : (newsBiasReport.market_context?.bb_position ?? 0.5) < 0.2 ? '#0ecb81' : '#f0b90b',
                  whiteSpace: 'nowrap', fontFamily: 'monospace',
                }">
                  {{ newsBiasReport.market_context?.bb_position != null ? (newsBiasReport.market_context.bb_position * 100).toFixed(0) + '%' : '-' }}
                </div>
                <div style="font-size: 10px; color: #666; margin-top: 2px; white-space: nowrap;">
                  {{ (newsBiasReport.market_context?.bb_position ?? 0.5) > 0.8 ? '⚠ 接近上轨' : (newsBiasReport.market_context?.bb_position ?? 0.5) < 0.2 ? '⚠ 接近下轨' : '中轨附近' }}
                </div>
              </div>
              <div style="padding: 0 8px; min-width: 0;">
                <div style="font-size: 10px; color: #888; white-space: nowrap;">当前实时</div>
                <div :style="{
                  fontSize: '17px', fontWeight: 700, marginTop: '4px',
                  color: livePrice ? '#0ecb81' : '#888',
                  whiteSpace: 'nowrap', fontFamily: 'monospace',
                }">
                  {{ livePrice?.bid?.toFixed(2) ?? '--' }}
                </div>
                <div style="font-size: 10px; color: #666; margin-top: 2px; white-space: nowrap;">
                  点差 {{ livePrice?.spread?.toFixed(2) ?? '--' }}
                  <n-button size="tiny" quaternary style="margin-left: 4px;" @click="refreshPrice">↻</n-button>
                </div>
              </div>
            </div>
          </n-card>

          <!-- ⑤ 验证结果 -->
          <n-card size="small" bordered style="margin-bottom: 12px;">
            <template #header>
              <span style="font-weight: 600;">⑤ 验证结果</span>
            </template>
            <div v-if="!newsBiasReport.verify_result" style="display: flex; align-items: center; gap: 12px; padding: 8px 0;">
              <n-spin size="small" />
              <div>
                <div style="color: #888;">等待验证（约 12 小时后自动比对）</div>
                <div style="font-size: 11px; color: #555; margin-top: 2px;">
                  验证逻辑：12h 后若价格变动 ≥ $0.5 视为方向成立；否则记为震荡
                </div>
              </div>
            </div>
            <div v-else style="display: flex; align-items: center; gap: 16px; padding: 8px 0; flex-wrap: wrap;">
              <n-tag :type="newsBiasReport.verify_result === 'correct' ? 'success' : 'error'" size="large" :bordered="false"
                style="font-size: 16px; padding: 6px 18px;">
                {{ newsBiasReport.verify_result === 'correct' ? '✓ 方向正确' : '✗ 方向错误' }}
              </n-tag>
              <div style="display: grid; grid-template-columns: repeat(4, auto); gap: 0 24px; align-items: center;">
                <div>
                  <div style="font-size: 11px; color: #888;">入场价</div>
                  <div style="font-size: 16px; font-weight: 700;">{{ newsBiasReport.entry_price?.toFixed(2) }}</div>
                </div>
                <div>
                  <div style="font-size: 11px; color: #888;">验证价</div>
                  <div style="font-size: 16px; font-weight: 700;">{{ newsBiasReport.verify_price?.toFixed(2) }}</div>
                </div>
                <div>
                  <div style="font-size: 11px; color: #888;">变动</div>
                  <div :style="{
                    fontSize: '16px', fontWeight: 700,
                    color: ((newsBiasReport.verify_price ?? 0) - (newsBiasReport.entry_price ?? 0)) >= 0 ? '#0ecb81' : '#f6465d',
                  }">
                    {{ ((newsBiasReport.verify_price ?? 0) - (newsBiasReport.entry_price ?? 0)) > 0 ? '+' : '' }}{{ ((newsBiasReport.verify_price ?? 0) - (newsBiasReport.entry_price ?? 0)).toFixed(2) }}
                  </div>
                </div>
                <div>
                  <div style="font-size: 11px; color: #888;">验证时间</div>
                  <div style="font-size: 13px; font-weight: 600;">{{ newsBiasReport.verify_at || '-' }}</div>
                </div>
              </div>
            </div>
          </n-card>

          <div style="text-align: center; padding: 12px 0; font-size: 11px; color: #555;">
            ⓘ 数据每 10 分钟自动更新；新闻由 RSS + 经济日历聚合
          </div>
        </template>
      </div>

      <!-- ══════════════════════════════════════════════════
           日报/周报 tab
           ══════════════════════════════════════════════════ -->
      <div v-else>
        <!-- 加载态 -->
        <div v-if="loading" style="display: flex; justify-content: center; padding: 80px 0;">
          <n-spin size="large" />
        </div>

        <!-- 错误态 -->
        <n-alert v-else-if="error" type="error" :title="error" closable style="margin-bottom: 16px;" />

        <!-- 空态 -->
        <n-empty v-else-if="!currentReport" description="选择左侧报告查看详情">
          <template #extra>
            <n-button size="small" secondary :loading="generating" @click="handleGenerate">
              生成报告
            </n-button>
          </template>
        </n-empty>

        <!-- 数据态 -->
        <template v-else>
          <div style="margin-bottom: 12px;">
            <div style="font-size: 18px; font-weight: 700;">{{ currentReport.title }}</div>
            <div style="font-size: 12px; color: #888; margin-top: 4px;">
              {{ fmtTimeFull(currentReport.created_at) }}
              <n-tag :type="activeTab === 'daily' ? 'info' : 'success'" size="tiny" :bordered="false" style="margin-left: 8px;">
                {{ activeTab === 'daily' ? '日报' : '周报' }}
              </n-tag>
            </div>
          </div>

        <!-- Sections 渲染 -->
        <template v-for="(sec, idx) in sections" :key="idx">
          <!-- ═══ 运行状态 ═══ -->
          <n-card v-if="sec.type === 'engine'" :title="sec.title" size="small" bordered
            style="margin-bottom: 8px;">
            <div style="display: flex; gap: 16px; flex-wrap: wrap;">
              <div>
                <span style="color: #888; font-size: 12px;">引擎状态 </span>
                <n-tag :type="sec.data.verdict === 'GREEN' ? 'success' : 'error'" size="small" :bordered="false">
                  {{ sec.data.status }}
                </n-tag>
              </div>
              <div>
                <span style="color: #888; font-size: 12px;">桥接 </span>
                <n-tag :type="sec.data.bridge === '已连接' ? 'success' : 'warning'" size="small" :bordered="false">
                  {{ sec.data.bridge }}
                </n-tag>
              </div>
              <div>
                <span style="color: #888; font-size: 12px;">运行时长 </span>
                <span style="font-weight: 600;">{{ sec.data.uptime }}</span>
              </div>
            </div>
          </n-card>

          <!-- ═══ 账户概况 ═══ -->
          <n-card v-else-if="sec.type === 'account'" :title="sec.title" size="small" bordered
            style="margin-bottom: 8px;">
            <n-grid :cols="6" :x-gap="16" :y-gap="12">
              <n-gi>
                <n-statistic label="余额" tabular-nums>
                  ${{ (sec.data.balance ?? 0).toFixed(2) }}
                </n-statistic>
              </n-gi>
              <n-gi>
                <n-statistic label="净值" tabular-nums>
                  ${{ (sec.data.equity ?? 0).toFixed(2) }}
                </n-statistic>
              </n-gi>
              <n-gi>
                <n-statistic label="保证金" tabular-nums>
                  ${{ (sec.data.margin ?? 0).toFixed(2) }}
                </n-statistic>
              </n-gi>
              <n-gi>
                <n-statistic label="可用保证金" tabular-nums>
                  ${{ (sec.data.free_margin ?? 0).toFixed(2) }}
                </n-statistic>
              </n-gi>
              <n-gi>
                <n-statistic label="浮动盈亏" tabular-nums>
                  <span :style="{ color: fmtPnlColor(sec.data.floating_pnl), fontWeight: 700 }">
                    {{ fmtPnl(sec.data.floating_pnl) }}
                  </span>
                </n-statistic>
              </n-gi>
              <n-gi>
                <n-statistic label="当日盈亏" tabular-nums>
                  <span :style="{ color: fmtPnlColor(sec.data.daily_pnl), fontWeight: 700 }">
                    {{ fmtPnl(sec.data.daily_pnl) }}
                  </span>
                </n-statistic>
              </n-gi>
            </n-grid>
          </n-card>

          <!-- ═══ 持仓 ═══ -->
          <n-card v-else-if="sec.type === 'positions'" :title="sec.title" size="small" bordered
            style="margin-bottom: 8px;">
            <div v-if="!sec.data || sec.data.length === 0">
              <n-empty description="无持仓" />
            </div>
            <n-data-table v-else :columns="[
              { title: '策略', key: 'strategy', width: 110,
                render: (r: any) => h(NTag, { size:'small', type:'warning', bordered:false }, () => r.strategy || '-') },
              { title: '方向', key: 'order_type', width: 70,
                render: (r: any) => h(NTag, { size:'small', type: r.order_type?.includes('BUY') ? 'success' : 'error', bordered:false }, () => r.order_type?.includes('BUY') ? '多头' : '空头') },
              { title: '手数', key: 'volume', width: 60 },
              { title: '开仓价', key: 'open_price', width: 90,
                render: (r: any) => r.open_price?.toFixed(2) },
              { title: '现价', key: 'current_price', width: 90,
                render: (r: any) => r.current_price?.toFixed(2) ?? '-' },
              { title: '浮盈', key: 'profit', width: 90,
                render: (r: any) => h('span', { style: { color: fmtPnlColor(r.profit ?? 0), fontWeight: 700 } }, fmtPnl(r.profit ?? 0)) },
            ]" :data="sec.data" size="small" :bordered="true" :max-height="300" striped />
          </n-card>

          <!-- ═══ 策略信号 ═══ -->
          <n-card v-else-if="sec.type === 'signals'" :title="sec.title" size="small" bordered
            style="margin-bottom: 8px;">
            <div v-if="!sec.data || sec.data.length === 0">
              <n-empty description="无信号数据" />
            </div>
            <n-space v-else vertical size="small">
              <n-card v-for="s in sec.data" :key="s.name" size="small" :bordered="true">
                <div style="font-size: 13px; line-height: 1.6;">
                  <!-- 策略名 + 信号 + 时间 -->
                  <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap;">
                    <span style="font-weight: 700;">{{ s.name }}</span>
                    <span>{{ s.signal === 'BUY' ? '🟢' : s.signal === 'SELL' ? '🔴' : '⚪' }} signal={{ s.signal || 'none' }}</span>
                    <n-tag v-if="s.time" size="tiny" :bordered="false" type="default">{{ s.time?.slice(11, 19) }}</n-tag>
                    <n-tag v-if="s.status === 'voided'" size="tiny" type="error" :bordered="false">废票 {{ s.void_reason }}</n-tag>
                    <n-tag v-else-if="s.status === 'opened'" size="tiny" type="success" :bordered="false">已开仓</n-tag>
                  </div>
                  <!-- 评分 + 阈值 -->
                  <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 4px;">
                    <span>L={{ s.score_long }} <span style="color: #888;">/ S={{ s.score_short }}</span></span>
                    <span v-if="s.threshold" style="color: #888;">
                      阈值={{ s.threshold }}
                      <n-tag v-if="s.threshold_reached" size="tiny" type="success" :bordered="false" style="margin-left: 4px;">已达标</n-tag>
                      <n-tag v-else size="tiny" type="default" :bordered="false" style="margin-left: 4px;">未达标</n-tag>
                    </span>
                  </div>
                  <!-- 因子明细 -->
                  <div v-if="s.factors_long?.length" style="margin-bottom: 2px;">
                    <span style="color: #0ecb81;">多头: </span>
                    <span v-for="(f, fi) in s.factors_long" :key="'lf'+fi">
                      <span v-if="fi > 0" style="color: #555;"> → </span>{{ f }}
                    </span>
                  </div>
                  <div v-if="s.factors_short?.length" style="margin-bottom: 2px;">
                    <span style="color: #f6465d;">空头: </span>
                    <span v-for="(f, fi) in s.factors_short" :key="'sf'+fi">
                      <span v-if="fi > 0" style="color: #555;"> → </span>{{ f }}
                    </span>
                  </div>
                  <!-- 指标快照 -->
                  <div style="color: #888; font-size: 12px; display: flex; gap: 12px; flex-wrap: wrap; margin-top: 4px;">
                    <span v-if="s.indicator_values?.close">价格={{ s.indicator_values.close.toFixed(1) }}</span>
                    <span v-if="s.indicator_values?.rsi">RSI={{ s.indicator_values.rsi.toFixed(1) }}</span>
                    <span v-if="s.indicator_values?.atr">ATR={{ s.indicator_values.atr.toFixed(1) }}</span>
                    <span v-if="s.indicator_values?.ema9">EMA9={{ s.indicator_values.ema9.toFixed(1) }}</span>
                    <span v-if="s.indicator_values?.ema21">EMA21={{ s.indicator_values.ema21.toFixed(1) }}</span>
                    <span v-if="s.indicator_values?.price_position">位置={{ (s.indicator_values.price_position * 100).toFixed(0) }}%</span>
                  </div>
                </div>
              </n-card>
            </n-space>
          </n-card>

          <!-- ═══ 风控状态 ═══ -->
          <n-card v-else-if="sec.type === 'risk'" :title="sec.title" size="small" bordered
            style="margin-bottom: 8px;">
            <div style="display: flex; gap: 24px; align-items: center;">
              <div>
                <span style="color: #888; font-size: 12px;">当日盈亏 </span>
                <span :style="{ color: fmtPnlColor(sec.data.daily_pnl), fontWeight: 700, fontSize: '16px' }">
                  {{ fmtPnl(sec.data.daily_pnl) }}
                </span>
              </div>
              <div>
                <span style="color: #888; font-size: 12px;">回撤 </span>
                <span style="font-weight: 600;">{{ (sec.data.daily_drawdown ?? 0).toFixed(2) }}%</span>
              </div>
              <div>
                <span style="color: #888; font-size: 12px;">阻断 </span>
                <n-tag v-if="!sec.data.strategy_blocks?.some((b: any) => b.blocks?.length)" size="small" type="success" :bordered="false">无</n-tag>
                <n-tag v-else size="small" type="warning" :bordered="false">
                  {{ sec.data.strategy_blocks.filter((b: any) => b.blocks?.length).length }} 个策略被阻断
                </n-tag>
              </div>
            </div>
            <div v-if="sec.data.strategy_blocks?.filter((b: any) => b.blocks?.length).length" style="margin-top: 8px; font-size: 12px; color: #f0a020;">
              <div v-for="b in sec.data.strategy_blocks.filter((b: any) => b.blocks?.length)" :key="b.magic">
                {{ b.strategy || `magic_${b.magic}` }}: {{ b.blocks.join(', ') }}
              </div>
            </div>
          </n-card>

          <!-- ═══ 行情快照 ═══ -->
          <n-card v-else-if="sec.type === 'market'" :title="sec.title" size="small" bordered
            style="margin-bottom: 8px;">
            <div style="display: flex; gap: 24px;">
              <div>
                <span style="color: #888; font-size: 12px;">买价 </span>
                <span style="font-weight: 700; font-size: 16px;">{{ (sec.data.bid ?? 0).toFixed(2) }}</span>
              </div>
              <div>
                <span style="color: #888; font-size: 12px;">卖价 </span>
                <span style="font-weight: 700; font-size: 16px;">{{ (sec.data.ask ?? 0).toFixed(2) }}</span>
              </div>
              <div>
                <span style="color: #888; font-size: 12px;">点差 </span>
                <span style="font-weight: 700; color: #f0b90b;">{{ (sec.data.spread ?? 0).toFixed(2) }}</span>
              </div>
            </div>
          </n-card>

          <!-- ═══ News-Bias 评估 ═══ -->
          <n-card v-else-if="sec.type === 'news_bias'" :title="sec.title" size="small" bordered
            style="margin-bottom: 8px;">
            <div style="display: flex; gap: 24px; margin-bottom: 12px;">
              <div>
                <span style="color: #888; font-size: 12px;">总计 </span>
                <span style="font-weight: 700;">{{ sec.data.total ?? 0 }} 条</span>
              </div>
              <div>
                <span style="color: #888; font-size: 12px;">方向性 </span>
                <span style="font-weight: 700;">{{ sec.data.directional ?? 0 }} 笔</span>
              </div>
              <div>
                <span style="color: #888; font-size: 12px;">准确率 </span>
                <span :style="{ color: (sec.data.accuracy ?? 0) >= 60 ? '#0ecb81' : '#f6465d', fontWeight: 700 }">
                  {{ sec.data.accuracy ?? 0 }}%
                </span>
              </div>
              <div>
                <span style="color: #888; font-size: 12px;">正确/错误 </span>
                <span style="font-weight: 700;">
                  <span style="color: #0ecb81;">{{ sec.data.correct ?? 0 }}</span>
                  /
                  <span style="color: #f6465d;">{{ sec.data.wrong ?? 0 }}</span>
                </span>
              </div>
              <div>
                <span style="color: #888; font-size: 12px;">中性(无法判断) </span>
                <span style="font-weight: 700; color: #888;">{{ sec.data.neutral ?? 0 }}</span>
              </div>
            </div>
            <div v-if="sec.data.evaluations?.length">
              <n-data-table :columns="[
                { title: '事件', key: 'event_title', width: 200,
                  render: (r: any) => r.event_title?.length > 30 ? r.event_title.slice(0, 30) + '…' : r.event_title },
                { title: '方向', key: 'expected_bias', width: 70,
                  render: (r: any) => h(NTag, { size:'small', type: r.expected_bias === 'bullish' ? 'success' : r.expected_bias === 'bearish' ? 'error' : 'default', bordered:false }, () => r.expected_bias === 'bullish' ? '利多' : r.expected_bias === 'bearish' ? '利空' : '中性') },
                { title: '置信度', key: 'confidence', width: 70 },
                { title: '实动15m', key: 'actual_move_15m', width: 90,
                  render: (r: any) => h('span', { style: { color: (r.actual_move_15m ?? 0) >= 0 ? '#0ecb81' : '#f6465d' } }, fmtPnl(r.actual_move_15m ?? 0)) },
                { title: '实动1h', key: 'actual_move_1h', width: 90,
                  render: (r: any) => h('span', { style: { color: (r.actual_move_1h ?? 0) >= 0 ? '#0ecb81' : '#f6465d' } }, fmtPnl(r.actual_move_1h ?? 0)) },
                { title: '判定', key: 'direction_match', width: 70,
                  render: (r: any) => r.direction_match ? h(NTag, { size:'small', type: r.direction_match === 'correct' ? 'success' : 'error', bordered:false }, () => r.direction_match === 'correct' ? '✓' : '✗') : h(NTag, { size:'small', type:'default', bordered:false }, () => '-') },
              ]" :data="sec.data.evaluations" size="small" :bordered="true" :max-height="300" striped />
            </div>
          </n-card>

          <!-- ═══ 最近成交 ═══ -->
          <n-card v-else-if="sec.type === 'trades'" :title="sec.title" size="small" bordered
            style="margin-bottom: 8px;">
            <div v-if="!sec.data || sec.data.length === 0">
              <n-empty description="无成交" />
            </div>
            <n-data-table v-else :columns="[
              { title: '时间', key: 'close_time', width: 140,
                render: (r: any) => fmtTimeFull(r.close_time) },
              { title: '策略', key: 'strategy', width: 100,
                render: (r: any) => h(NTag, { size:'small', type:'warning', bordered:false }, () => r.strategy) },
              { title: '方向', key: 'order_type', width: 60,
                render: (r: any) => h(NTag, { size:'small', type: r.order_type?.includes('BUY') ? 'success' : 'error', bordered:false }, () => r.order_type?.includes('BUY') ? '多头' : '空头') },
              { title: '盈亏', key: 'pnl', width: 100,
                render: (r: any) => h('span', { style: { color: fmtPnlColor(r.pnl ?? 0), fontWeight: 700 } }, fmtPnl(r.pnl ?? 0)) },
              { title: '出场原因', key: 'exit_reason', width: 100,
                render: (r: any) => h(NTag, { size:'small', bordered:false }, () => r.exit_reason || '-') },
            ]" :data="sec.data" size="small" :bordered="true" :max-height="300" striped />
          </n-card>

          <!-- ═══ 周报汇总 ═══ -->
          <n-card v-else-if="sec.type === 'weekly_summary'" :title="sec.title" size="small" bordered
            style="margin-bottom: 8px;">
            <n-grid :cols="6" :x-gap="16" :y-gap="12">
              <n-gi>
                <n-statistic label="总盈亏" tabular-nums>
                  <span :style="{ color: fmtPnlColor(sec.data.total_pnl), fontWeight: 700 }">{{ fmtPnl(sec.data.total_pnl) }}</span>
                </n-statistic>
              </n-gi>
              <n-gi><n-statistic label="笔数" tabular-nums>{{ sec.data.count ?? 0 }}</n-statistic></n-gi>
              <n-gi><n-statistic label="胜率" tabular-nums>{{ sec.data.win_rate ?? 0 }}%</n-statistic></n-gi>
              <n-gi><n-statistic label="胜/负" tabular-nums>{{ sec.data.wins ?? 0 }}/{{ sec.data.losses ?? 0 }}</n-statistic></n-gi>
              <n-gi><n-statistic label="最大盈利" tabular-nums>${{ (sec.data.best ?? 0).toFixed(2) }}</n-statistic></n-gi>
              <n-gi><n-statistic label="最大亏损" tabular-nums>${{ Math.abs(sec.data.worst ?? 0).toFixed(2) }}</n-statistic></n-gi>
            </n-grid>
          </n-card>

          <!-- ═══ 按策略分组 ═══ -->
          <n-card v-else-if="sec.type === 'by_strategy'" :title="sec.title" size="small" bordered
            style="margin-bottom: 8px;">
            <div v-if="!sec.data || Object.keys(sec.data).length === 0">
              <n-empty description="无数据" />
            </div>
            <n-space v-else vertical size="small">
              <n-card v-for="(s, name) in sec.data" :key="name as string" size="small" :bordered="true">
                <div style="display: flex; gap: 24px;">
                  <div style="font-weight: 700; min-width: 120px;">{{ name }}</div>
                  <div>
                    PnL: <span :style="{ color: fmtPnlColor(s.pnl), fontWeight: 700 }">{{ fmtPnl(s.pnl) }}</span>
                  </div>
                  <div>{{ s.count }} 笔</div>
                  <div>胜率 {{ s.win_rate ?? 0 }}%</div>
                </div>
              </n-card>
            </n-space>
          </n-card>

          <!-- fallback -->
          <n-card v-else :title="sec.title || '未知区块'" size="small" bordered
            style="margin-bottom: 8px;">
            <pre style="font-size: 12px; color: #888;">{{ sec }}</pre>
          </n-card>
        </template>
        </template>
      </div>
    </div>
  </div>
</template>
