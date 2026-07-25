<script setup lang="ts">
import { ref, computed, h, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { darkTheme, NIcon } from 'naive-ui'
import {
  AnalyticsOutline, WalletOutline, SettingsOutline, DocumentTextOutline,
  BarChartOutline, PowerOutline, PlayOutline, StopOutline,
  ReaderOutline, CalendarNumberOutline,
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

// 新闻弹窗
const showNewsBias = ref(false)
const newsBiasData = ref<any>(null)
const titleText = computed(() => newsBiasData.value?.title || 'XAUUSD 新闻预判')
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
      updateResult.value = `发现 ${v.behind_count} 个新 commit`
    } else {
      loadChangelog()
      updateResult.value = '已是最新'
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
      updateResult.value = '✅ 更新成功！'
      remoteChangelog.value = []
    } else {
      updateResult.value = `❌ ${r.message}`
    }
  } catch (e: any) {
    updateResult.value = `❌ ${e?.message || '更新失败'}`
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
  { label: '交易终端', key: '/', icon: renderIcon(AnalyticsOutline) },
  { label: '账户持仓', key: '/positions', icon: renderIcon(WalletOutline) },
  { label: '策略中心', key: '/strategies', icon: renderIcon(BarChartOutline) },
  { label: '历史成交', key: '/trades', icon: renderIcon(ReaderOutline) },
  { label: '运行配置', key: '/config', icon: renderIcon(SettingsOutline) },
  { label: '日报周报', key: '/report', icon: renderIcon(CalendarNumberOutline) },
  { label: '系统日志', key: '/logs', icon: renderIcon(DocumentTextOutline) },
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
      title: '确认停止引擎',
      content: '停止引擎后所有策略暂停运行，确定继续？',
      positiveText: '确定',
      negativeText: '取消',
      onPositiveClick: async () => {
        toggleLoading.value = true
        try {
          await stopEngine()
          engineStatus.value = 'stopped'
          message.success('引擎已停止')
        } catch (e: any) {
          message.error(e?.response?.data?.detail || '停止失败')
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
      message.success('引擎启动成功')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '启动失败')
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
  <n-layout position="absolute" style="height: 100vh;">
    <n-layout has-sider position="absolute" style="height: 100vh;">
      <!-- 侧边栏 -->
      <n-layout-sider bordered collapse-mode="width" :collapsed-width="64" :width="220"
        :collapsed="collapsed" @collapse="collapsed = true" @expand="collapsed = false"
        :native-scrollbar="false" style="background: #1a1d23;">
        <div style="padding: 20px 16px 12px; text-align: center;">
          <n-h2 style="margin: 0; color: #f0b90b;" prefix="bar">
            <n-text v-if="!collapsed" style="color: #f0b90b; font-size: 22px; font-weight: 700;">XAUUSD</n-text>
            <n-text v-else style="color: #f0b90b; font-size: 18px; font-weight: 700;">X</n-text>
          </n-h2>
          <n-text v-if="!collapsed" depth="3" style="font-size: 11px;">量化交易仪表盘</n-text>
        </div>

        <n-menu :value="route.path" :options="menuOptions" :collapsed="collapsed"
                :collapsed-width="64" :collapsed-icon-size="22"
                @update:value="handleMenuUpdate" />
      </n-layout-sider>

      <!-- 主内容 -->
      <n-layout>
        <n-layout-header bordered style="height: 48px; display: flex; align-items: center; padding: 0 20px; gap: 12px;">
          <n-button quaternary size="small" @click="collapsed = !collapsed">
            <template #icon>
              <n-icon><BarChartOutline /></n-icon>
            </template>
          </n-button>
          <n-breadcrumb>
            <n-breadcrumb-item>XAUUSD 量化交易系统</n-breadcrumb-item>
            <n-breadcrumb-item>{{ route.name === 'config' ? '配置' : route.name === 'positions' ? '持仓' : route.name === 'strategies' ? '策略' : route.name === 'logs' ? '日志' : route.name === 'patrol' ? '监控' : '仪表板' }}</n-breadcrumb-item>
          </n-breadcrumb>
          <div style="flex:1;"></div>
          <n-tooltip trigger="hover" placement="bottom">
            <template #trigger>
              <div class="version-badge" @click="openChangelog" style="
                display: inline-flex; align-items: center; gap: 4px;
                padding: 2px 8px; border-radius: 10px;
                background: rgba(240, 185, 11, 0.12);
                color: #f0b90b; font-size: 11px; font-weight: 600;
                cursor: pointer; font-family: ui-monospace, SFMono-Regular, monospace;
                border: 1px solid rgba(240, 185, 11, 0.3);
              ">
                <span style="font-size: 9px;">●</span>
                <span>v{{ versionInfo.version }}</span>
                <span v-if="versionInfo.has_update" style="color: #f6465d; font-size: 9px;">●</span>
                <span v-if="versionInfo.behind_count > 0" style="color: #f0b90b; opacity: 0.7;">({{ versionInfo.behind_count }})</span>
                <span v-else style="color: #22c55e; font-size: 10px;">✓</span>
              </div>
            </template>
            <div style="font-size: 12px; line-height: 1.5;">
              <div><b>分支:</b> {{ versionInfo.branch }}</div>
              <div><b>提交:</b> {{ versionInfo.commit }}</div>
              <div v-if="versionInfo.has_update" style="color: #f6465d;">⬆ 有 {{ versionInfo.behind_count }} 个新 commit 可更新</div>
              <div v-else style="color: #22c55e;">✓ 已是最新版本</div>
              <div v-if="versionInfo.dirty" style="color: #888; margin-top: 2px;">* 本地有未提交修改</div>
              <div style="color: #888; margin-top: 4px;">点击查看详情</div>
            </div>
          </n-tooltip>
          <PatrolIndicator />
          <n-switch :value="engineStatus === 'running'" size="large" :round="true"
            :loading="toggleLoading" @update:value="toggleEngine">
            <template #checked-icon>
              <span class="engine-dot" :class="{ 'pulse-flash': wsPulse }" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#22c55e;"></span>
            </template>
          </n-switch>
        </n-layout-header>

        <n-layout-content content-style="padding: 20px 24px;" :native-scrollbar="false"
                          style="height: calc(100vh - 48px);">
          <router-view />
        </n-layout-content>
      </n-layout>
    </n-layout>
  </n-layout>

    <!-- 新闻预判弹窗 -->
    <div v-if="showNewsBias" class="nb-overlay" @click.self="closePopup">
      <div class="nb-modal">
        <div class="nb-modal-header">
          <span style="font-weight: 700; font-size: 16px;" v-text="titleText"></span>
          <button class="nb-close" @click="closePopup">X</button>
        </div>
        <div class="nb-modal-body">
          <NewsBiasPopup v-if="newsBiasData" :data="newsBiasData" @close="closePopup"></NewsBiasPopup>
        </div>
      </div>
    </div>

    <!-- 版本变更日志弹窗 -->
    <n-modal v-model:show="showChangelog" preset="card" style="width: 640px; max-width: 90vw;"
             :title="versionInfo.has_update ? `版本更新 — v${versionInfo.version} → 落后 ${versionInfo.behind_count} 个 commit` : `版本信息 — v${versionInfo.version} 已是最新`">
      <template #header-extra>
        <n-tag size="small" :bordered="false" type="success" v-if="!versionInfo.has_update">已是最新</n-tag>
        <n-tag size="small" :bordered="false" type="warning" v-else>有更新</n-tag>
      </template>

      <!-- 有更新时：远程 changelog + 更新按钮 -->
      <div v-if="versionInfo.has_update">
        <div v-if="loadingRemote" style="text-align: center; color: #888; padding: 20px;">加载中...</div>
        <div v-else style="max-height: 50vh; overflow-y: auto;">
          <div v-for="(c, i) in remoteChangelog" :key="i"
               style="display: flex; gap: 12px; padding: 8px 4px; border-bottom: 1px solid #1f1f1f;">
            <div style="font-family: ui-monospace, monospace; color: #f0b90b; font-size: 11px; min-width: 64px;">
              {{ c.hash }}
            </div>
            <div style="color: #666; font-size: 11px; min-width: 130px; font-family: ui-monospace, monospace;">
              {{ c.date?.slice(0, 16) }}
            </div>
            <div style="flex: 1; font-size: 13px; color: #ddd; line-height: 1.5;">
              {{ c.subject }}
            </div>
          </div>
        </div>
        <div v-if="updateResult" style="margin-top: 12px; font-size: 12px;" :style="{color: updateResult.includes('成功') || updateResult.includes('最新') ? '#22c55e' : '#f6465d'}">{{ updateResult }}</div>
      </div>

      <!-- 无更新时：本地 changelog -->
      <div v-else>
        <div style="margin-bottom: 12px; display: flex; gap: 16px; font-size: 12px; color: #888;">
          <span>当前版本: <b style="color: #ddd;">v{{ versionInfo.version }}</b></span>
          <span>提交: <b style="color: #ddd;">{{ versionInfo.commit }}</b></span>
          <span>分支: <b style="color: #ddd;">{{ versionInfo.branch }}</b></span>
        </div>
        <div v-if="!changelog.length" style="text-align: center; color: #888; padding: 20px;">
          加载中...
        </div>
        <div v-else style="max-height: 40vh; overflow-y: auto;">
          <div v-for="(c, i) in changelog" :key="i"
               style="display: flex; gap: 12px; padding: 8px 4px; border-bottom: 1px solid #1f1f1f;">
            <div style="font-family: ui-monospace, monospace; color: #f0b90b; font-size: 11px; min-width: 64px;">
              {{ c.hash }}
            </div>
            <div style="color: #666; font-size: 11px; min-width: 130px; font-family: ui-monospace, monospace;">
              {{ c.date?.slice(0, 16) }}
            </div>
            <div style="flex: 1; font-size: 13px; color: #ddd; line-height: 1.5;">
              {{ c.subject }}
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: #888;">
          <span v-if="versionInfo.has_update">待更新 {{ versionInfo.behind_count }} 个 commit</span>
          <span v-else>最近 {{ changelog.length }} 条 commit</span>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span v-if="versionInfo.dirty && versionInfo.has_update" style="color: #f0b90b;">⚠ 本地有未提交修改</span>
            <n-button size="small" quaternary :loading="loadingRemote" @click="checkUpdate">↻ 检查更新</n-button>
            <n-button size="small" type="warning" secondary :disabled="!versionInfo.has_update || versionInfo.dirty" :loading="updating" @click="doUpdate">
              ⬇ 版本更新
            </n-button>
          </div>
        </div>
      </template>
    </n-modal>
</template>

<style scoped>
.engine-dot.pulse-flash {
  box-shadow: 0 0 8px 3px rgba(34,197,94,.8);
}
.nb-overlay {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0,0,0,0.6);
  display: flex; align-items: center; justify-content: center;
}
.nb-modal {
  background: #1a1d23; border-radius: 8px;
  max-width: 600px; width: 90%; max-height: 80vh;
  display: flex; flex-direction: column;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
}
.nb-modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px; border-bottom: 1px solid #2a2a2a;
}
.nb-close {
  background: none; border: none; color: #888; font-size: 24px;
  cursor: pointer; padding: 0 4px; line-height: 1;
}
.nb-close:hover { color: #fff; }
.nb-modal-body {
  padding: 20px; overflow-y: auto;
}
</style>
