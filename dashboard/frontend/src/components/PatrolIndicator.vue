<script setup lang="ts">
import { usePatrolStore } from '@/stores/patrol'

const patrol = usePatrolStore()

const dotColor: Record<string, string> = {
  normal: '#22c55e',
  warning: '#eab308',
  critical: '#ef4444',
}
const labelText: Record<string, string> = {
  normal: '监控正常',
  warning: `${patrol.warningCount} 条告警`,
  critical: `${patrol.criticalCount} 条严重告警`,
}
</script>

<template>
  <div style="padding: 4px 16px 8px; display: flex; align-items: center; gap: 8px; cursor: pointer;"
    @click="$router.push('/patrol')">
    <span :style="{
      display: 'inline-block',
      width: '8px',
      height: '8px',
      borderRadius: '50%',
      backgroundColor: dotColor[patrol.health],
      flexShrink: 0,
    }" />
    <n-text depth="3" style="font-size: 11px; line-height: 1.3;">
      {{ labelText[patrol.health] || '监控正常' }}
    </n-text>
    <n-badge v-if="patrol.unreadCount > 0" :value="patrol.unreadCount" :max="99" type="warning" />
  </div>
</template>
