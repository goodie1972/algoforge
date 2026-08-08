<script setup lang="ts">
import { ref, computed, h, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { darkTheme, NIcon } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import {
  AnalyticsOutline, WalletOutline, SettingsOutline, DocumentTextOutline,
  BarChartOutline, PowerOutline, PlayOutline, StopOutline,
  ReaderOutline, CalendarNumberOutline,
  MoonOutline, SunnyOutline, LanguageOutline,
} from '@vicons/ionicons5'
import { useAccountStore } from '@/stores/account'
import { usePositionStore } from '@/stores/positions'
import { usePriceStore } from '@/stores/prices'
import { useLogStore } from '@/stores/logs'
import { usePatrolStore } from '@/stores/patrol'
import { wsClient } from '@/api/websocket'
import { getEngineStatus, startEngine, stopEngine, getVersionInfo, getChangelog, getRemoteChangelog, updateVersion } from '@/api/client'
import { useMessage, useDialog } from 'naive-ui'
import PatrolIndicator from '@/components/PatrolIndicator.vue'
import NewsBiasPopup from '@/components/NewsBiasPopup.vue'

const { t, locale } = useI18n()
const appStore = useAppStore()

// 监听语言变化，刷新菜单
const menuKey = ref(0)
watch(() => locale.value, () => { menuKey.value++ })
// 同步 appStore locale 到 i18n
watch(() => appStore.locale, (val) => { if (val) locale.value = val }, { immediate: true })

// 新闻弹窗
const showNewsBias = ref(false)
const newsBiasData = ref<any>(null)
const titleText = computed(() => newsBiasData.value?.title || t('app.news_title'))
function closePopup() { showNewsBias.value = false }




const router = useRouter()
const route = useRoute()
const accountStore = useAccountStore()
const positionStore = usePositionStore()
const priceStore = usePriceStore()
const logStore = useLogStore()
const patrolStore = usePatrolStore()

const engineStatus = ref<'running' | 'stopped'>('stopped')
const toggleLoading = ref(false)
const message = useMessage()
const dialog = useDialog()
const wsPulse = ref(false)
let pulseTimer: ReturnType<typeof setTimeout> | null = null

// 版本信息
const versionInfo = ref<{version: string; commit: string; branch: string; dirty: boolean; display: string; has_update: boolean; behind_count: number}>({
  version: '0.0.0', commit: '?', branch: '?', dirty: false, display: 'v0.0.0', has_update: false, behind_count: 0,
})
const showChangelog = ref(false)
const changelog = ref<Array<{hash: string; date: string; subject: string}>>([])
const updating = ref(false)
const updateResult = ref<string>('')
const updateOk = ref(false)
async function loadChangelog() {
  try {
    const r = await getChangelog(20)
    changelog.value = r.commits || []
  } catch { /* ignore */ }
}
const remoteChangelog = ref<Array<{hash: string; date: string; subject: string}>>([])
const loadingRemote = ref(false)
async function loadRemoteChangelog() {
  loadingRemote.value = true
  try {
    const r = await getRemoteChangelog(20)
    remoteChangelog.value = r.commits || []
  } catch { /* ignore */ }
  loadingRemote.value = false
}
async function openChangelog() {
  showChangelog.value = true
  updateResult.value = ''
  checkUpdate()
}
async function checkUpdate() {
  updateResult.value = ''
  try {
    const v = await getVersionInfo()
    versionInfo.value = v as any
    if (v.has_update) {
      loadRemoteChangelog()
      updateResult.value = t('app.found_new_commits', { count: v.behind_count })
      updateOk.value = false
    } else {
      loadChangelog()
      updateResult.value = t('app.up_to_date')
      updateOk.value = true
    }
  } catch { /* ignore */ }
}
async function doUpdate() {
  updating.value = true
  updateResult.value = ''
  try {
    const r = await updateVersion()
    if (r.success && r.version) {
      versionInfo.value = r.version as any
      updateResult.value = t('app.update_success')
      updateOk.value = true
      remoteChangelog.value = []
    } else {
      updateResult.value = t('app.update_failed', { message: r.message })
      updateOk.value = false
    }
  } catch (e: any) {
    updateResult.value = t('app.update_failed', { message: e?.message || t('app.update_failed_msg') })
    updateOk.value = false
  }
  updating.value = false
}
let updateCheckTimer: ReturnType<typeof setInterval> | null = null
function triggerPulse() {
  wsPulse.value = true
  if (pulseTimer) clearTimeout(pulseTimer)
  pulseTimer = setTimeout(() => { wsPulse.value = false }, 400)
}
const collapsed = ref(false)

function renderIcon(icon: any) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

const menuOptions = [
  { label: () => t('nav.trading'), key: '/', icon: renderIcon(AnalyticsOutline) },
  { label: () => t('nav.positions'), key: '/positions', icon: renderIcon(WalletOutline) },
  { label: () => t('nav.strategies'), key: '/strategies', icon: renderIcon(BarChartOutline) },
  { label: () => t('nav.trades'), key: '/trades', icon: renderIcon(ReaderOutline) },
  { label: () => t('nav.config'), key: '/config', icon: renderIcon(SettingsOutline) },
  { label: () => t('nav.report'), key: '/report', icon: renderIcon(CalendarNumberOutline) },
  { label: () => t('nav.logs'), key: '/logs', icon: renderIcon(DocumentTextOutline) },
]

function handleMenuUpdate(key: string) {
  router.push(key)
}

async function checkEngineStatus() {
  try {
    const st = await getEngineStatus()
    engineStatus.value = st.status === 'running' ? 'running' : 'stopped'
  } catch { /* ignore */ }
}

async function toggleEngine(checked: boolean) {
  if (!checked) {
    dialog.warning({
      title: t('engine.confirm_stop'),
      content: t('engine.confirm_stop_msg'),
      positiveText: t('common.confirm'),
      negativeText: t('common.cancel'),
      onPositiveClick: async () => {
        toggleLoading.value = true
        try {
          await stopEngine()
          engineStatus.value = 'stopped'
          message.success(t('engine.stop_success'))
        } catch (e: any) {
          message.error(e?.response?.data?.detail || t('engine.stop_fail'))
          engineStatus.value = 'running'
        }
        toggleLoading.value = false
      },
      onNegativeClick: () => {
        engineStatus.value = 'running'
      }
    })
  } else {
    toggleLoading.value = true
    try {
      await startEngine()
      engineStatus.value = 'running'
      message.success(t('engine.start_success'))
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('engine.start_fail'))
      engineStatus.value = 'stopped'
    }
    toggleLoading.value = false
  }
}

onMounted(() => {
  checkEngineStatus()
  patrolStore.start(30000)
  accountStore.fetch()
  logStore.fetchHistory()
  getVersionInfo().then((v) => { versionInfo.value = v as any }).catch(() => { /* keep default */ })
  // 每 5 分钟检查远程更新
  updateCheckTimer = setInterval(() => {
    getVersionInfo().then((v) => { versionInfo.value = v as any }).catch(() => {})
  }, 300000)

  wsClient.connect()
  wsClient.on('prices', (msg) => { priceStore.updateTick(msg.data.bid, msg.data.ask); triggerPulse() })
  wsClient.on('positions', (msg) => { positionStore.updateFromWs(msg.data); triggerPulse() })
  wsClient.on('account', (msg) => accountStore.updateFromWs(msg.data))
  wsClient.on('logs', (msg) => logStore.append(msg.data))
  wsClient.on('status', (msg) => {
    engineStatus.value = msg.data?.status === 'running' ? 'running' : 'stopped'
    toggleLoading.value = false
  })
  wsClient.on('news_bias_popup', (msg) => {
    newsBiasData.value = msg.data || msg
    showNewsBias.value = true
  })
})

onUnmounted(() => {
  wsClient.disconnect()
  patrolStore.stop()
  if (updateCheckTimer) clearInterval(updateCheckTimer)
})
</script>

<template>
  <n-layout position="absolute" class="app-shell">
    <n-layout has-sider position="absolute" class="app-shell">
      <!-- 侧边栏 -->
      <n-layout-sider bordered collapse-mode="width" :collapsed-width="64" :width="220"
        :collapsed="collapsed" @collapse="collapsed = true" @expand="collapsed = false"
        :native-scrollbar="false" class="app-sider">
        <div class="sider-header">
          <n-h2 prefix="bar" class="sider-title">
            <svg v-if="!collapsed" class="sider-logo-svg" viewBox="0 0 32 32" width="28" height="28">
              <defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#f0b90b"/><stop offset="100%" stop-color="#d4a309"/></linearGradient></defs>
              <circle cx="16" cy="16" r="12.5" fill="url(#lg)"/>
              <path d="M16 1 L6 16 L14 16 L6 31 L26 16 L18 16 L26 1 Z" fill="url(#lg)" stroke="#1c2333" stroke-width="1.5" stroke-linejoin="round"/>
            </svg>
            <span v-if="!collapsed" class="sider-logo-text">AlgoForge</span>
            <svg v-else class="sider-logo-svg" viewBox="0 0 32 32" width="28" height="28">
              <defs><linearGradient id="lg2" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#f0b90b"/><stop offset="100%" stop-color="#d4a309"/></linearGradient></defs>
              <circle cx="16" cy="16" r="12.5" fill="url(#lg2)"/>
              <path d="M16 1 L6 16 L14 16 L6 31 L26 16 L18 16 L26 1 Z" fill="url(#lg2)" stroke="#1c2333" stroke-width="1.5" stroke-linejoin="round"/>
            </svg>
          </n-h2>
          <n-text v-if="!collapsed" depth="3" class="sider-subtitle">{{ t('app.subtitle') }}</n-text>
        </div>

        <n-menu :value="route.path" :options="menuOptions" :collapsed="collapsed"
                :collapsed-width="64" :collapsed-icon-size="22"
                :key="menuKey"
                @update:value="handleMenuUpdate" />

        <!-- 侧边栏底部：主题/语言切换 -->
        <div class="sider-footer">
          <n-button quaternary size="small" @click="appStore.toggleTheme()" class="sider-toggle-btn">
            <template #icon>
              <n-icon><component :is="appStore.isDark ? SunnyOutline : MoonOutline" /></n-icon>
            </template>
            <span v-if="!collapsed">{{ appStore.isDark ? t('theme.light') : t('theme.dark') }}</span>
          </n-button>
          <n-button quaternary size="small" @click="appStore.setLocale(locale === 'zh-CN' ? 'en-US' : 'zh-CN')" class="sider-toggle-btn">
            <template #icon>
              <n-icon><LanguageOutline /></n-icon>
            </template>
            <span v-if="!collapsed">{{ locale === 'zh-CN' ? t('lang.en') : t('lang.zh') }}</span>
          </n-button>
        </div>
      </n-layout-sider>

      <!-- 主内容 -->
      <n-layout>
        <n-layout-header bordered class="app-header">
          <n-button quaternary size="small" @click="collapsed = !collapsed">
            <template #icon>
              <n-icon><BarChartOutline /></n-icon>
            </template>
          </n-button>
          <n-breadcrumb>
            <n-breadcrumb-item>{{ t('app.breadcrumb') }}</n-breadcrumb-item>
            <n-breadcrumb-item>{{ route.name === 'config' ? t('common.config') : route.name === 'positions' ? t('common.positions') : route.name === 'strategies' ? t('common.strategies') : route.name === 'logs' ? t('common.logs') : route.name === 'patrol' ? t('common.patrol') : t('common.dashboard') }}</n-breadcrumb-item>
          </n-breadcrumb>
          <div class="header-spacer"></div>
          <n-tooltip trigger="hover" placement="bottom">
            <template #trigger>
              <div class="version-badge" @click="openChangelog">
                <span class="version-dot">●</span>
                <span>v{{ versionInfo.version }}</span>
                <span v-if="versionInfo.has_update" class="version-dot-update">●</span>
                <span v-if="versionInfo.behind_count > 0" class="version-behind">({{ versionInfo.behind_count }})</span>
                <span v-else class="version-current">✓</span>
              </div>
            </template>
            <div class="version-tooltip">
              <div><b>{{ t('version.branch') }}:</b> {{ versionInfo.branch }}</div>
              <div><b>{{ t('version.commit') }}:</b> {{ versionInfo.commit }}</div>
              <div v-if="versionInfo.has_update" class="version-update-available">⬆ {{ t('version.update_available', {count: versionInfo.behind_count}) }}</div>
              <div v-else class="version-up-to-date">✓ {{ t('version.latest') }}</div>
              <div v-if="versionInfo.dirty" class="version-dirty">* {{ t('version.local_dirty') }}</div>
              <div class="version-click-hint">{{ t('version.click_hint') }}</div>
            </div>
          </n-tooltip>
          <PatrolIndicator />
          <n-switch :value="engineStatus === 'running'" size="large" :round="true"
            :loading="toggleLoading" @update:value="toggleEngine">
            <template #checked-icon>
              <span class="engine-dot" :class="{ 'pulse-flash': wsPulse }"></span>
            </template>
          </n-switch>
        </n-layout-header>

        <n-layout-content class="app-content" :native-scrollbar="false">
          <router-view />
        </n-layout-content>
      </n-layout>
    </n-layout>
  </n-layout>

    <!-- 新闻预判弹窗 -->
    <div v-if="showNewsBias" class="nb-overlay" @click.self="closePopup">
      <div class="nb-modal">
        <div class="nb-modal-header">
          <span class="nb-modal-title" v-text="titleText"></span>
          <button class="nb-close" @click="closePopup">X</button>
        </div>
        <div class="nb-modal-body">
          <NewsBiasPopup v-if="newsBiasData" :data="newsBiasData" @close="closePopup"></NewsBiasPopup>
        </div>
      </div>
    </div>

    <!-- 版本变更日志弹窗 -->
    <n-modal v-model:show="showChangelog" preset="card" class="changelog-modal"
             :title="versionInfo.has_update ? `v${versionInfo.version} — ${t('version.update_available', {count: versionInfo.behind_count})}` : `${t('version.title')} — v${versionInfo.version} ${t('version.latest')}`">
      <template #header-extra>
        <n-tag size="small" :bordered="false" type="success" v-if="!versionInfo.has_update">{{ t('version.up_to_date') }}</n-tag>
        <n-tag size="small" :bordered="false" type="warning" v-else>{{ t('version.has_update') }}</n-tag>
      </template>

      <div v-if="versionInfo.has_update">
        <div v-if="loadingRemote" class="changelog-loading">{{ t('version.loading') }}</div>
        <div v-else class="changelog-list">
          <div v-for="(c, i) in remoteChangelog" :key="i" class="changelog-item">
            <div class="cl-hash">{{ c.hash }}</div>
            <div class="cl-date">{{ c.date?.slice(0, 16) }}</div>
            <div class="cl-subject">{{ c.subject }}</div>
          </div>
        </div>
        <div v-if="updateResult" class="update-result" :class="updateOk ? 'update-success' : 'update-fail'">{{ updateResult }}</div>
      </div>

      <div v-else>
        <div class="version-info-bar">
          <span>{{ t('version.current') }}: <b class="version-highlight">v{{ versionInfo.version }}</b></span>
          <span>{{ t('version.commit') }}: <b class="version-highlight">{{ versionInfo.commit }}</b></span>
          <span>{{ t('version.branch') }}: <b class="version-highlight">{{ versionInfo.branch }}</b></span>
        </div>
        <div v-if="!changelog.length" class="changelog-loading">{{ t('version.loading') }}</div>
        <div v-else class="changelog-list">
          <div v-for="(c, i) in changelog" :key="i" class="changelog-item">
            <div class="cl-hash">{{ c.hash }}</div>
            <div class="cl-date">{{ c.date?.slice(0, 16) }}</div>
            <div class="cl-subject">{{ c.subject }}</div>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="changelog-footer">
          <span v-if="versionInfo.has_update" class="footer-text">{{ t('version.pending_commits', {count: versionInfo.behind_count}) }}</span>
          <span v-else class="footer-text">{{ t('version.recent_commits', {count: changelog.length}) }}</span>
          <div class="footer-actions">
            <span v-if="versionInfo.dirty && versionInfo.has_update" class="footer-dirty-warning">⚠ {{ t('version.local_dirty') }}</span>
            <n-button size="small" quaternary :loading="loadingRemote" @click="checkUpdate">↻ {{ t('version.check_update') }}</n-button>
            <n-button size="small" type="warning" secondary :disabled="!versionInfo.has_update || versionInfo.dirty" :loading="updating" @click="doUpdate">
              ⬇ {{ t('version.do_update') }}
            </n-button>
          </div>
        </div>
      </template>
    </n-modal>
</template>

<style scoped>
/* ── 布局 ── */
.app-shell {
  height: 100vh;
  width: 100%;
  left: 0;
}
.app-sider {
  background: var(--n-color, #1a1d23);
}
.app-header {
  height: 48px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 12px;
}
.app-content {
  height: calc(100vh - 48px);
  padding: 20px 24px;
}
.header-spacer {
  flex: 1;
}

/* ── 侧边栏 ── */
.sider-header {
  padding: 20px 16px 12px;
  text-align: center;
}
.sider-title {
  margin: 0;
  color: #f0b90b;
}
.sider-logo-svg {
  display: inline-block;
  vertical-align: middle;
  margin-right: 6px;
  flex-shrink: 0;
}
.sider-logo-text {
  color: #f0b90b;
  font-size: 22px;
  font-weight: 700;
  vertical-align: middle;
}
.sider-subtitle {
  font-size: 11px;
}

/* ── 侧边栏底部切换按钮 ── */
.sider-footer {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 8px;
  display: flex;
  gap: 4px;
  justify-content: center;
  border-top: 1px solid var(--n-border-color, #2d3139);
}
.sider-toggle-btn {
  flex: 1;
  font-size: 12px !important;
}

/* ── 版本号徽标 ── */
.version-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(240, 185, 11, 0.12);
  color: #f0b90b;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  font-family: ui-monospace, SFMono-Regular, monospace;
  border: 1px solid rgba(240, 185, 11, 0.3);
  transition: background 0.2s ease, border-color 0.2s ease;
}
.version-badge:hover {
  background: rgba(240, 185, 11, 0.2);
  border-color: rgba(240, 185, 11, 0.5);
}
.version-dot {
  font-size: 9px;
}
.version-dot-update {
  color: #f6465d;
  font-size: 9px;
}
.version-behind {
  color: #f0b90b;
  opacity: 0.7;
}
.version-current {
  color: #22c55e;
  font-size: 10px;
}

/* ── 版本 tooltip ── */
.version-tooltip {
  font-size: 12px;
  line-height: 1.5;
}
.version-update-available {
  color: #f6465d;
}
.version-up-to-date {
  color: #22c55e;
}
.version-dirty {
  color: #888;
  margin-top: 2px;
}
.version-click-hint {
  color: #888;
  margin-top: 4px;
}

/* ── 引擎状态点 ── */
.engine-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
}
.engine-dot.pulse-flash {
  box-shadow: 0 0 8px 3px rgba(34,197,94,.8);
}

/* ── 新闻弹窗 ── */
.nb-overlay {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0,0,0,0.6);
  display: flex; align-items: center; justify-content: center;
}
.nb-modal {
  background: #1a1d23; border-radius: 12px;
  max-width: 600px; width: 90%; max-height: 80vh;
  display: flex; flex-direction: column;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
}
.nb-modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px; border-bottom: 1px solid #2a2a2a;
}
.nb-modal-title {
  font-weight: 700;
  font-size: 16px;
}
.nb-close {
  background: none; border: none; color: #888; font-size: 24px;
  cursor: pointer; padding: 0 4px; line-height: 1;
  transition: color 0.15s ease;
}
.nb-close:hover { color: #fff; }
.nb-modal-body {
  padding: 20px; overflow-y: auto;
}

/* ── Changelog 弹窗 ── */
.changelog-modal {
  width: 640px;
  max-width: 90vw;
}
.changelog-loading {
  text-align: center;
  color: #888;
  padding: 20px;
}
.changelog-list {
  max-height: 50vh;
  overflow-y: auto;
}
.changelog-item {
  display: flex;
  gap: 12px;
  padding: 8px 4px;
  border-bottom: 1px solid #1f1f1f;
}
.cl-hash {
  font-family: ui-monospace, monospace;
  color: #f0b90b;
  font-size: 11px;
  min-width: 64px;
}
.cl-date {
  color: #666;
  font-size: 11px;
  min-width: 130px;
  font-family: ui-monospace, monospace;
}
.cl-subject {
  flex: 1;
  font-size: 13px;
  color: #ddd;
  line-height: 1.5;
}
.update-result {
  margin-top: 12px;
  font-size: 12px;
}
.update-success {
  color: #22c55e;
}
.update-fail {
  color: #f6465d;
}
.version-info-bar {
  margin-bottom: 12px;
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #888;
}
.version-highlight {
  color: #ddd;
}
.changelog-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  color: #888;
}
.footer-text {
  color: #888;
}
.footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.footer-dirty-warning {
  color: #f0b90b;
}
</style>
