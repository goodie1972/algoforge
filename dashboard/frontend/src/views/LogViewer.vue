<script setup lang="ts">
import { ref, onMounted, computed, watch, nextTick } from 'vue'
import { useLogStore } from '@/stores/logs'

const store = useLogStore()
const logContainer = ref<HTMLDivElement>()
const autoScroll = ref(true)

const levelOptions = [
  { label: '全部', value: null },
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
]

onMounted(() => store.fetchHistory())

const displayLogs = computed(() => store.filteredEntries)

function scrollToNewest() {
  if (autoScroll.value && logContainer.value) {
    nextTick(() => {
      logContainer.value!.scrollTop = logContainer.value!.scrollHeight
    })
  }
}

watch(() => store.entries.length, () => {
  if (!logContainer.value) return
  if (logContainer.value.scrollTop >= logContainer.value.scrollHeight - logContainer.value.clientHeight - 50) {
    scrollToNewest()
  }
})

function onScroll(e: Event) {
  const el = e.target as HTMLElement
  const atBottom = el.scrollTop >= el.scrollHeight - el.clientHeight - 50
  autoScroll.value = atBottom
}

function logStyle(level: string) {
  switch (level) {
    case 'ERROR': return { color: '#f6465d' }
    case 'WARNING': return { color: '#f0b90b' }
    case 'INFO': return { color: '#1e70bf' }
    default: return { color: '#8b8f97' }
  }
}
</script>

<template>
  <n-space vertical size="large">
    <div class="log-header">
      <n-h2 class="log-title">系统日志</n-h2>
      <n-space size="small" align="center">
        <n-radio-group :value="store.filterLevel" @update:value="(v: any) => store.filterLevel = v">
          <n-radio-button v-for="opt in levelOptions" :key="opt.value || 'all'" :value="opt.value">
            {{ opt.label }}
          </n-radio-button>
        </n-radio-group>
        <n-checkbox v-model:checked="autoScroll">自动滚动</n-checkbox>
        <n-button size="small" quaternary @click="store.clear()">清空</n-button>
      </n-space>
    </div>

    <n-card :bordered="true" size="small" class="log-card">
      <!-- 日志列表 - 始终渲染，不销毁容器 -->
      <div ref="logContainer" class="log-list" @scroll="onScroll">
        <!-- 空态 -->
        <n-empty v-if="displayLogs.length === 0" description="暂无日志" class="log-empty" />
        <div v-for="entry in displayLogs" :key="entry._id"
             class="log-entry"
             @mouseenter="($event.target as HTMLElement).style.background = '#2c3038'"
             @mouseleave="($event.target as HTMLElement).style.background = 'transparent'">
          <span class="log-time">{{ entry.timestamp?.slice(11, 23) || entry.timestamp || '' }}</span>
          <span :style="{ ...logStyle(entry.level), flexShrink: 0, width: 60, fontWeight: 600 }">{{ entry.level }}</span>
          <span class="log-name">{{ entry.name }}</span>
          <span class="log-msg">{{ entry.message }}</span>
        </div>
      </div>
    </n-card>
  </n-space>
</template>

<style scoped>
.log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.log-title {
  margin: 0;
}
.log-card {
  padding: 0;
}
.log-empty {
  padding: 40px 0;
}
.log-list {
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.7;
  height: calc(100vh - 220px);
  overflow-y: auto;
}
.log-entry {
  padding: 1px 12px;
  display: flex;
  gap: 8px;
  white-space: nowrap;
}
.log-time {
  color: #8b8f97;
  flex-shrink: 0;
}
.log-name {
  color: #8b8f97;
  flex-shrink: 0;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.log-msg {
  color: #d4d7dd;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
