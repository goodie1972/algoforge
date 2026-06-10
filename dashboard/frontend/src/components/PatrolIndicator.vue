<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { NIcon } from 'naive-ui'
import { NotificationsOutline, AlertCircleOutline, WarningOutline } from '@vicons/ionicons5'
import { usePatrolStore } from '@/stores/patrol'

const props = withDefaults(defineProps<{ collapsed?: boolean }>(), { collapsed: false })
const router = useRouter()
const patrol = usePatrolStore()
const showPopover = ref(false)

const levelColor: Record<string, string> = {
  normal: '#22c55e',
  warning: '#eab308',
  critical: '#ef4444',
}

const tagInfo: Record<string, { type: 'success' | 'warning' | 'error'; text: string }> = {
  normal: { type: 'success', text: '正常' },
  warning: { type: 'warning', text: `${patrol.warningCount} 告警` },
  critical: { type: 'error', text: `${patrol.criticalCount} 紧急` },
}

// 警报音
let audioCtx: AudioContext | null = null
function playAlarm() {
  try {
    if (!audioCtx) audioCtx = new AudioContext()
    const osc = audioCtx.createOscillator()
    const gain = audioCtx.createGain()
    osc.connect(gain)
    gain.connect(audioCtx.destination)
    osc.type = 'square'
    osc.frequency.setValueAtTime(880, audioCtx.currentTime)
    osc.frequency.setValueAtTime(660, audioCtx.currentTime + 0.12)
    gain.gain.setValueAtTime(0.3, audioCtx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.35)
    osc.start(audioCtx.currentTime)
    osc.stop(audioCtx.currentTime + 0.35)
  } catch { /* browser may block */ }
}

let prevCritical = patrol.criticalCount
watch(() => patrol.criticalCount, (n) => {
  if (n > prevCritical) playAlarm()
  prevCritical = n
})

onUnmounted(() => { audioCtx?.close(); audioCtx = null })
</script>

<template>
  <!-- 侧边栏折叠模式：简化为小圆点，点击跳 PatrolView -->
  <div v-if="props.collapsed" style="padding: 4px 0; display: flex; justify-content: center;">
    <div class="bell-btn" @click="router.push('/patrol')" title="监控告警">
      <n-icon :color="levelColor[patrol.health]" size="20">
        <NotificationsOutline />
      </n-icon>
    </div>
  </div>

  <!-- 正常模式：铃铛 + 下拉弹窗 -->
  <n-popover v-else trigger="click" :show="showPopover" placement="bottom-end" :width="380"
    @update:show="(v: boolean) => showPopover = v">
    <template #trigger>
      <div class="bell-btn"
        :class="{ 'bell-critical': patrol.health === 'critical', 'bell-warning': patrol.health === 'warning' }"
        @click="showPopover = !showPopover"
        title="监控告警">
        <n-badge :value="patrol.unreadCount" :max="99"
          :type="patrol.health === 'critical' ? 'error' : patrol.health === 'warning' ? 'warning' : 'success'"
          :show="patrol.unreadCount > 0">
          <n-icon :color="levelColor[patrol.health]" size="22">
            <NotificationsOutline />
          </n-icon>
        </n-badge>
      </div>
    </template>

    <!-- 下拉告警列表 -->
    <div class="popover-content">
      <div class="popover-header">
        <n-space align="center" size="small">
          <n-icon :color="levelColor[patrol.health]" size="18">
            <AlertCircleOutline v-if="patrol.health === 'critical'" />
            <WarningOutline v-else-if="patrol.health === 'warning'" />
            <NotificationsOutline v-else />
          </n-icon>
          <n-text strong style="font-size: 14px;">监控告警</n-text>
          <n-tag :type="tagInfo[patrol.health].type" size="tiny" :bordered="false">
            {{ tagInfo[patrol.health].text }}
          </n-tag>
        </n-space>
        <n-space size="small">
          <n-button size="tiny" quaternary @click="patrol.runPatrol()">刷新</n-button>
          <n-button size="tiny" quaternary @click="patrol.clearAlerts()">清除</n-button>
        </n-space>
      </div>

      <n-divider style="margin: 8px 0;" />

      <div v-if="patrol.alerts.length === 0" style="text-align: center; padding: 20px 0;">
        <n-icon :color="'#22c55e'" size="32"><NotificationsOutline /></n-icon>
        <n-text depth="3" style="display: block; margin-top: 8px; font-size: 13px;">无告警，一切正常</n-text>
      </div>

      <div v-else class="alert-list">
        <div v-for="a in patrol.alerts.slice(0, 15)" :key="a.id" class="alert-row"
          :style="{ borderLeftColor: a.level === 'critical' ? '#ef4444' : a.level === 'warning' ? '#eab308' : '#22c55e' }">
          <span class="alert-time">{{ a.time }}</span>
          <n-tag :type="a.level === 'critical' ? 'error' : a.level === 'warning' ? 'warning' : 'success'"
            size="tiny" :bordered="false" style="flex-shrink: 0;">
            {{ a.level === 'critical' ? '严重' : a.level === 'warning' ? '告警' : '信息' }}
          </n-tag>
          <span class="alert-msg">{{ a.message }}</span>
        </div>
      </div>

      <div v-if="patrol.alerts.length > 15" style="text-align: center; margin-top: 4px;">
        <n-text depth="3" style="font-size: 11px;">还有 {{ patrol.alerts.length - 15 }} 条...</n-text>
      </div>

      <n-divider style="margin: 8px 0;" />
      <div style="text-align: center;">
        <n-button size="tiny" text @click="showPopover = false; router.push('/patrol')">
          查看全部 →
        </n-button>
        <n-text depth="3" style="font-size: 11px; margin-left: 8px;">
          上次: {{ patrol.lastCheckTime }}
        </n-text>
      </div>
    </div>
  </n-popover>
</template>

<style scoped>
.bell-btn {
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  transition: all .2s;
}
.bell-btn:hover {
  background: rgba(255,255,255,.08);
}
/* warning: 黄色脉冲 */
.bell-warning {
  animation: bell-pulse 2s infinite;
}
@keyframes bell-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(234,179,8,0); }
  50% { box-shadow: 0 0 8px 2px rgba(234,179,8,.4); }
}
/* critical: 红色旋转 + 发光 */
.bell-critical {
  animation: bell-shake 0.6s infinite, bell-glow 1s infinite;
}
@keyframes bell-shake {
  0%, 100% { transform: rotate(0deg); }
  15% { transform: rotate(12deg); }
  30% { transform: rotate(-10deg); }
  45% { transform: rotate(8deg); }
  60% { transform: rotate(-6deg); }
  75% { transform: rotate(3deg); }
  90% { transform: rotate(-1deg); }
}
@keyframes bell-glow {
  0%, 100% { box-shadow: 0 0 4px 1px rgba(239,68,68,.3); }
  50% { box-shadow: 0 0 16px 4px rgba(239,68,68,.7); }
}

.popover-content {
  max-height: 500px;
  display: flex;
  flex-direction: column;
}
.popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.alert-list {
  overflow-y: auto;
  max-height: 340px;
}
.alert-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 5px 6px;
  font-size: 12px;
  border-left: 3px solid;
  margin-bottom: 2px;
  background: rgba(255,255,255,.02);
  border-radius: 0 4px 4px 0;
  min-width: 0;
}
.alert-time {
  flex-shrink: 0;
  color: #888;
  font-size: 11px;
  min-width: 52px;
}
.alert-msg {
  flex: 1;
  min-width: 0;
  word-break: break-word;
  overflow-wrap: break-word;
  line-height: 1.4;
}
</style>
