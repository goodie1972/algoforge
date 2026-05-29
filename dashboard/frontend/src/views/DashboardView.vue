<script setup lang="ts">
import { ref } from 'vue'
import { useMessage } from 'naive-ui'
import { getEngineStatus, startEngine, stopEngine } from '@/api/client'
import { PlayOutline, StopOutline } from '@vicons/ionicons5'
import AccountPanel from '@/components/dashboard/AccountPanel.vue'
import PriceChart from '@/components/dashboard/PriceChart.vue'
import PositionsTable from '@/components/dashboard/PositionsTable.vue'
import StrategySignals from '@/components/dashboard/StrategySignals.vue'

const message = useMessage()
const loading = ref(false)
const engineStatus = ref<'running' | 'stopped'>('stopped')

async function refreshStatus() {
  try {
    const st = await getEngineStatus()
    engineStatus.value = st.status === 'running' ? 'running' : 'stopped'
  } catch { /* ignore */ }
}

refreshStatus()

async function toggleEngine() {
  loading.value = true
  try {
    if (engineStatus.value === 'running') {
      await stopEngine()
      engineStatus.value = 'stopped'
      message.success('引擎已停止')
    } else {
      await startEngine()
      engineStatus.value = 'running'
      message.success('引擎启动成功')
    }
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || '操作失败')
  }
  loading.value = false
}
</script>

<template>
  <n-space vertical size="large">
    <!-- 引擎控制栏 -->
    <n-card :bordered="true" size="small">
      <n-space align="center" justify="space-between">
        <n-space align="center">
          <n-tag :type="engineStatus === 'running' ? 'success' : 'default'" round size="medium" :bordered="false">
            <template #icon>
              <n-icon><div :style="{
                width: 8, height: 8, borderRadius: '50%',
                background: engineStatus === 'running' ? '#0ecb81' : '#8b8f97',
              }" /></n-icon>
            </template>
            {{ engineStatus === 'running' ? '引擎运行中' : '引擎已停止' }}
          </n-tag>
        </n-space>
        <n-button :type="engineStatus === 'running' ? 'error' : 'primary'"
                  :loading="loading" @click="toggleEngine">
          <template #icon>
            <n-icon><component :is="engineStatus === 'running' ? StopOutline : PlayOutline" /></n-icon>
          </template>
          {{ engineStatus === 'running' ? '停止引擎' : '启动引擎' }}
        </n-button>
      </n-space>
    </n-card>

    <!-- 账户信息 -->
    <AccountPanel />

    <!-- 图表 + 信号 -->
    <n-grid :cols="3" :x-gap="16">
      <n-gi :span="2"><PriceChart /></n-gi>
      <n-gi><StrategySignals /></n-gi>
    </n-grid>

    <!-- 持仓 -->
    <PositionsTable />
  </n-space>
</template>
