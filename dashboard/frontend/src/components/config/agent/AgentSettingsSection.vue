<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'

const { t } = useI18n()
const message = useMessage()

const toolsEnabled = ref(false)
const memoryAutoAccumulate = ref(false)
const loaded = ref(false)
const savingField = ref('')

async function loadSettings() {
  try {
    const res = await fetch('/api/ai/agent-settings')
    if (!res.ok) return
    const d = await res.json()
    toolsEnabled.value = !!d.tools_enabled
    memoryAutoAccumulate.value = !!d.memory_auto_accumulate
    loaded.value = true
  } catch { /* ignore */ }
}

async function putSetting(field: 'tools_enabled' | 'memory_auto_accumulate', value: boolean) {
  savingField.value = field
  try {
    const res = await fetch('/api/ai/agent-settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: value }),
    })
    let d: any = {}
    try { d = await res.json() } catch { /* 响应体非 JSON */ }
    // 同时检查 HTTP 状态码与响应体错误字段，失败时回滚开关
    if (!res.ok || d.error || d.detail) {
      const detail = d.error || d.detail || res.statusText || `HTTP ${res.status}`
      message.error(`${t('ai.save_failed', { error: '' })}: ${detail}`)
      if (field === 'tools_enabled') toolsEnabled.value = !value
      else memoryAutoAccumulate.value = !value
      return
    }
    toolsEnabled.value = !!d.tools_enabled
    memoryAutoAccumulate.value = !!d.memory_auto_accumulate
    message.success(t('ai.saved'))
  } catch {
    message.error(t('ai.save_failed', { error: '' }))
    if (field === 'tools_enabled') toolsEnabled.value = !value
    else memoryAutoAccumulate.value = !value
  } finally { savingField.value = '' }
}

onMounted(loadSettings)
</script>

<template>
  <n-card :title="t('ai.agent_settings_title')" size="small" :bordered="true">
    <n-space vertical size="large">
      <div class="agent-setting-row">
        <div class="agent-setting-info">
          <div class="agent-setting-label">{{ t('ai.agent_tools_enabled') }}</div>
          <div class="agent-setting-desc">{{ t('ai.agent_tools_desc') }}</div>
        </div>
        <n-switch :value="toolsEnabled" :loading="savingField === 'tools_enabled'"
          :disabled="!loaded" @update:value="(v: boolean) => putSetting('tools_enabled', v)" />
      </div>
      <div class="agent-setting-row">
        <div class="agent-setting-info">
          <div class="agent-setting-label">{{ t('ai.agent_memory_auto') }}</div>
          <div class="agent-setting-desc">{{ t('ai.agent_memory_desc') }}</div>
        </div>
        <n-switch :value="memoryAutoAccumulate" :loading="savingField === 'memory_auto_accumulate'"
          :disabled="!loaded" @update:value="(v: boolean) => putSetting('memory_auto_accumulate', v)" />
      </div>
    </n-space>
  </n-card>
</template>

<style scoped>
.agent-setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.agent-setting-info {
  flex: 1;
  min-width: 0;
}
.agent-setting-label {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 2px;
}
.agent-setting-desc {
  font-size: 12px;
  color: #8b8f97;
  line-height: 1.5;
}
</style>
