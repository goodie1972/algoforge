<script setup lang="ts">
import { ref, h, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { darkTheme, NIcon } from 'naive-ui'
import {
  AnalyticsOutline, WalletOutline, SettingsOutline, DocumentTextOutline,
  BarChartOutline, PowerOutline, PlayOutline, StopOutline, TimeOutline,
} from '@vicons/ionicons5'
import { useAccountStore } from '@/stores/account'
import { usePositionStore } from '@/stores/positions'
import { usePriceStore } from '@/stores/prices'
import { useLogStore } from '@/stores/logs'
import { wsClient } from '@/api/websocket'
import { getEngineStatus } from '@/api/client'

const router = useRouter()
const route = useRoute()
const accountStore = useAccountStore()
const positionStore = usePositionStore()
const priceStore = usePriceStore()
const logStore = useLogStore()

const engineStatus = ref<'running' | 'stopped'>('stopped')
const collapsed = ref(false)

function renderIcon(icon: any) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

const menuOptions = [
  { label: '交易终端', key: '/', icon: renderIcon(AnalyticsOutline) },
  { label: '账户持仓', key: '/positions', icon: renderIcon(WalletOutline) },
  { label: '策略中心', key: '/strategies', icon: renderIcon(BarChartOutline) },
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

onMounted(() => {
  checkEngineStatus()
  // WebSocket 推送覆盖大部分数据，仅需少量 REST 初始加载
  accountStore.fetch()
  logStore.fetchHistory()

  wsClient.connect()
  wsClient.on('prices', (msg) => priceStore.updateTick(msg.data.bid, msg.data.ask))
  wsClient.on('positions', (msg) => positionStore.updateFromWs(msg.data))
  wsClient.on('account', (msg) => accountStore.updateFromWs(msg.data))
  wsClient.on('logs', (msg) => logStore.append(msg.data))
  wsClient.on('status', (msg) => {
    engineStatus.value = msg.data?.status === 'running' ? 'running' : 'stopped'
  })
})

onUnmounted(() => {
  wsClient.disconnect()
})

</script>

<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="{
    common: { primaryColor: '#f0b90b', primaryColorHover: '#f5c532', primaryColorPressed: '#d4a309' }
  }">
    <n-message-provider>
      <n-notification-provider>
        <n-dialog-provider>
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

              <!-- 引擎状态指示器 -->
              <div style="padding: 8px 16px 12px; display: flex; align-items: center; gap: 8px;"
                   :style="collapsed ? 'justify-content:center;' : ''">
                <n-badge :type="engineStatus === 'running' ? 'success' : 'default'" dot />
                <n-text v-if="!collapsed" depth="3" style="font-size: 12px;">
                  {{ engineStatus === 'running' ? '引擎运行中' : '引擎已停止' }}
                </n-text>
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
                  <n-breadcrumb-item>{{ route.name === 'config' ? '配置' : route.name === 'positions' ? '持仓' : route.name === 'strategies' ? '策略' : route.name === 'logs' ? '日志' : '仪表板' }}</n-breadcrumb-item>
                </n-breadcrumb>
                <div style="flex:1;"></div>
                <n-tag :type="engineStatus === 'running' ? 'success' : 'default'" size="small" :bordered="false">
                  {{ engineStatus === 'running' ? '● 运行中' : '○ 已停止' }}
                </n-tag>
              </n-layout-header>

              <n-layout-content content-style="padding: 20px 24px;" :native-scrollbar="false"
                                style="height: calc(100vh - 48px);">
                <router-view />
              </n-layout-content>
            </n-layout>
          </n-layout>
        </n-layout>
      </n-dialog-provider>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>
