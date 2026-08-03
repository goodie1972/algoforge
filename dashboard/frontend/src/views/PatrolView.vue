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
    <n-page-header :subtitle="$t('patrol.subtitle')">
      <template #title>
        <n-space align="center" size="small">
          <n-icon :color="levelColors[patrol.health]" size="28">
            <AlertCircleOutline v-if="patrol.health === 'critical'" />
            <WarningOutline v-else-if="patrol.health === 'warning'" />
            <ShieldCheckmarkOutline v-else />
          </n-icon>
          <span>{{ $t('patrol.status') }}</span>
          <n-tag v-if="patrol.health === 'normal'" type="success" size="small" :bordered="false">{{ $t('patrol.all_ok') }}</n-tag>
          <n-tag v-else-if="patrol.health === 'warning'" type="warning" size="small" :bordered="false">
            {{ $t('patrol.warning_count', { count: patrol.warningCount }) }}
          </n-tag>
          <n-tag v-else type="error" size="small" :bordered="false">
            {{ $t('patrol.critical_count', { count: patrol.criticalCount }) }}
          </n-tag>
        </n-space>
      </template>
      <template #extra>
        <n-space>
          <n-button size="small" @click="patrol.runPatrol()">{{ $t('patrol.run_now') }}</n-button>
          <n-button size="small" @click="patrol.clearAlerts()">{{ $t('patrol.clear_alerts') }}</n-button>
        </n-space>
      </template>
    </n-page-header>

    <n-p v-if="patrol.lastCheckTime" depth="3" style="font-size: 12px;">
              {{ $t('patrol.last_check') }}: {{ patrol.lastCheckTime }}
    </n-p>

    <!-- 空状态 -->
    <n-empty v-if="patrol.alerts.length === 0" :description="$t('patrol.empty')" style="margin-top: 40px;">
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
                {{ a.level === 'critical' ? $t('patrol.level_critical') : a.level === 'warning' ? $t('patrol.level_warning') : $t('patrol.level_info') }}
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
