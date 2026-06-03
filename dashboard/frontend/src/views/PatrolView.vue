<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { usePatrolStore } from '@/stores/patrol'
import { ShieldCheckmarkOutline, AlertCircleOutline, WarningOutline } from '@vicons/ionicons5'

const patrol = usePatrolStore()

onMounted(() => {
  patrol.start(30000)
})

onUnmounted(() => {
  patrol.stop()
})

const levelColors: Record<string, string> = {
  info: '#22c55e',
  warning: '#eab308',
  critical: '#ef4444',
}
const levelIcons: Record<string, any> = {
  info: ShieldCheckmarkOutline,
  warning: WarningOutline,
  critical: AlertCircleOutline,
}
</script>

<template>
  <div>
    <n-page-header subtitle="监控告警">
      <template #title>
        <n-space align="center" size="small">
          <n-icon :color="levelColors[patrol.health]" size="28">
            <AlertCircleOutline v-if="patrol.health === 'critical'" />
            <WarningOutline v-else-if="patrol.health === 'warning'" />
            <ShieldCheckmarkOutline v-else />
          </n-icon>
          <span>巡检状态</span>
          <n-tag v-if="patrol.health === 'normal'" type="success" size="small" :bordered="false">一切正常</n-tag>
          <n-tag v-else-if="patrol.health === 'warning'" type="warning" size="small" :bordered="false">
            {{ patrol.warningCount }} 条告警
          </n-tag>
          <n-tag v-else type="error" size="small" :bordered="false">
            {{ patrol.criticalCount }} 条严重
          </n-tag>
        </n-space>
      </template>
      <template #extra>
        <n-space>
          <n-button size="small" @click="patrol.runPatrol()">立即巡检</n-button>
          <n-button size="small" @click="patrol.clearAlerts()">清除告警</n-button>
        </n-space>
      </template>
    </n-page-header>

    <n-p v-if="patrol.lastCheckTime" depth="3" style="font-size: 12px;">
      上次巡检: {{ patrol.lastCheckTime }}
    </n-p>

    <!-- 空状态 -->
    <n-empty v-if="patrol.alerts.length === 0" description="无告警，一切正常" style="margin-top: 40px;">
      <template #icon>
        <n-icon :color="'#22c55e'" size="48">
          <ShieldCheckmarkOutline />
        </n-icon>
      </template>
    </n-empty>

    <!-- 告警列表 -->
    <n-list v-else style="margin-top: 16px;">
      <n-list-item v-for="a in patrol.alerts" :key="a.id">
        <n-thing>
          <template #avatar>
            <n-icon :color="levelColors[a.level]" size="20">
              <AlertCircleOutline v-if="a.level === 'critical'" />
              <WarningOutline v-else-if="a.level === 'warning'" />
              <ShieldCheckmarkOutline v-else />
            </n-icon>
          </template>
          <template #header>
            <n-space align="center" size="small">
              <n-tag :type="a.level === 'critical' ? 'error' : a.level === 'warning' ? 'warning' : 'success'"
                size="tiny" :bordered="false">
                {{ a.level === 'critical' ? '严重' : a.level === 'warning' ? '告警' : '信息' }}
              </n-tag>
              <span>{{ a.time }}</span>
            </n-space>
          </template>
          {{ a.message }}
        </n-thing>
      </n-list-item>
    </n-list>
  </div>
</template>
