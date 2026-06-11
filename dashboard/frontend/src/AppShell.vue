<script setup lang="ts">
import { ref, h, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { darkTheme, NIcon } from 'naive-ui'
import {
  AnalyticsOutline, WalletOutline, SettingsOutline, DocumentTextOutline,
  BarChartOutline, PowerOutline, PlayOutline, StopOutline,
  ReaderOutline,
} from '@vicons/ionicons5'
import { useAccountStore } from '@/stores/account'
import { usePositionStore } from '@/stores/positions'
import { usePriceStore } from '@/stores/prices'
import { useLogStore } from '@/stores/logs'
import { usePatrolStore } from '@/stores/patrol'
import { wsClient } from '@/api/websocket'
import { getEngineStatus, startEngine, stopEngine } from '@/api/client'
import { useMessage, useDialog } from 'naive-ui'
import PatrolIndicator from '@/components/PatrolIndicator.vue'

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

  wsClient.connect()
  wsClient.on('prices', (msg) => { priceStore.updateTick(msg.data.bid, msg.data.ask); triggerPulse() })
  wsClient.on('positions', (msg) => { positionStore.updateFromWs(msg.data); triggerPulse() })
  wsClient.on('account', (msg) => accountStore.updateFromWs(msg.data))
  wsClient.on('logs', (msg) => logStore.append(msg.data))
  wsClient.on('status', (msg) => {
    engineStatus.value = msg.data?.status === 'running' ? 'running' : 'stopped'
    toggleLoading.value = false
  })
})

onUnmounted(() => {
  wsClient.disconnect()
  patrolStore.stop()
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
</template>

<style scoped>
.engine-dot.pulse-flash {
  box-shadow: 0 0 8px 3px rgba(34,197,94,.8);
}
</style>
