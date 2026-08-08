<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'

const { t } = useI18n()
const message = useMessage()

const providers = ref<any[]>([])
const activeProvider = ref<any>(null)
const loading = ref(false)
const selectedProviderId = ref<string | null>(null)
const testing = ref(false)
const saving = ref(false)

const form = ref({
  name: '',
  type: 'openai',
  api_key: '',
  base_url: 'https://api.openai.com/v1',
  models: [] as string[],
  enabled_models: [] as string[],
  selected_model: '',
})

const selectedProvider = computed(() => {
  if (!selectedProviderId.value) return null
  return providers.value.find(p => p.id === selectedProviderId.value) || null
})

async function loadProviders() {
  loading.value = true
  try {
    const [listRes, activeRes] = await Promise.all([
      fetch('/api/llm/providers'),
      fetch('/api/llm/active'),
    ])
    const listData = await listRes.json()
    const activeData = await activeRes.json()
    if (listData.success) providers.value = listData.data
    if (activeData.success) activeProvider.value = activeData.data
  } catch (e) {
    console.error('加载 Provider 失败', e)
  } finally {
    loading.value = false
  }
}

function selectProvider(id: string) {
  selectedProviderId.value = id
  const p = providers.value.find(x => x.id === id)
  if (!p) return
  form.value = {
    name: p.name,
    type: p.type,
    api_key: p.api_key || '',
    base_url: p.base_url,
    models: p.models || [],
    enabled_models: p.enabled_models || [],
    selected_model: p.selected_model || '',
  }
}

function addProvider() {
  selectedProviderId.value = 'new'
  form.value = {
    name: '',
    type: 'openai',
    api_key: '',
    base_url: 'https://api.openai.com/v1',
    models: [],
    enabled_models: [],
    selected_model: '',
  }
}

async function saveProvider() {
  if (!form.value.name) { message.warning(t('ai.name_required')); return }
  saving.value = true
  try {
    const body = {
      name: form.value.name, type: form.value.type,
      api_key: form.value.api_key, base_url: form.value.base_url,
      models: form.value.models, enabled_models: form.value.enabled_models,
      selected_model: form.value.selected_model,
    }
    if (selectedProviderId.value === 'new') {
      const res = await fetch('/api/llm/providers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const d = await res.json()
      if (d.success) { message.success(t('ai.add')); selectedProviderId.value = d.data.id }
    } else {
      const res = await fetch(`/api/llm/providers/${selectedProviderId.value}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const d = await res.json()
      if (d.success) message.success(t('ai.saved'))
    }
    await loadProviders()
  } catch (e: any) { message.error(t('ai.save_failed', { error: e.message || '' })) }
  finally { saving.value = false }
}

async function deleteProvider(id: string) {
  try {
    const res = await fetch(`/api/llm/providers/${id}`, { method: 'DELETE' })
    const d = await res.json()
    if (d.success) { message.success(t('ai.deleted')); if (selectedProviderId.value === id) selectedProviderId.value = null; await loadProviders() }
  } catch { message.error(t('ai.delete_failed')) }
}

async function activateProvider(id: string) {
  try {
    const res = await fetch(`/api/llm/providers/${id}/activate`, { method: 'POST' })
    const d = await res.json()
    if (d.success) { message.success(t('ai.activated')); await loadProviders() }
  } catch { message.error(t('ai.activate_failed')) }
}

function toggleModel(model: string) {
  const idx = form.value.enabled_models.indexOf(model)
  if (idx >= 0) {
    form.value.enabled_models.splice(idx, 1)
    if (form.value.selected_model === model) form.value.selected_model = form.value.enabled_models[0] || ''
  } else {
    form.value.enabled_models.push(model)
    if (!form.value.selected_model) form.value.selected_model = model
  }
}

async function testConnection() {
  if (!form.value.base_url) { message.warning(t('ai.api_url_required')); return }
  if (form.value.type !== 'ollama' && !form.value.api_key) { message.warning(t('ai.api_key_required')); return }
  testing.value = true
  try {
    let id = selectedProviderId.value
    if (id === 'new' || !id) {
      const r = await fetch('/api/llm/providers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: form.value.name || 'temp', type: form.value.type, api_key: form.value.api_key, base_url: form.value.base_url }) })
      const d = await r.json()
      if (!d.success) { message.error(t('ai.save_failed')); return }
      id = d.data.id; selectedProviderId.value = id
    } else {
      await fetch(`/api/llm/providers/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ api_key: form.value.api_key, base_url: form.value.base_url }) })
    }
    const res = await fetch(`/api/llm/providers/${id}/test`, { method: 'POST' })
    const d = await res.json()
    if (d.success && d.data?.models?.length) {
      form.value.models = d.data.models
      form.value.enabled_models = [...d.data.models]
      form.value.selected_model = d.data.models[0]
      message.success(t('ai.test_success', { count: d.data.models.length }))
    } else if (d.success) {
      message.success(t('ai.connection_success'))
    } else {
      message.error(t('ai.test_failed'))
    }
  } catch (e: any) { message.error(t('ai.test_failed_error', { error: e.message || '' })) }
  finally { testing.value = false }
}

function providerIcon(type: string): string { return type === 'ollama' ? '🦙' : '🤖' }

onMounted(loadProviders)
</script>

<template>
  <div style="display:flex;gap:0;height:calc(100vh - 260px);min-height:420px;border:1px solid var(--n-border-color);border-radius:8px;overflow:hidden">
    <!-- 左侧列表 -->
    <div style="width:200px;flex-shrink:0;border-right:1px solid var(--n-border-color);overflow-y:auto;padding:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px">
        <span style="font-weight:600;font-size:13px">{{ t('ai.providers') }}</span>
        <n-button size="tiny" quaternary circle @click="addProvider" style="font-size:16px;line-height:1">+</n-button>
      </div>
      <n-spin :show="loading" size="small">
        <n-empty v-if="!loading && providers.length === 0" :description="t('ai.no_providers')" size="small" />
        <div v-for="p in providers" :key="p.id" @click="selectProvider(p.id)"
          style="display:flex;align-items:center;gap:8px;padding:8px;border-radius:6px;cursor:pointer;margin-bottom:2px;transition:background 0.2s"
          :style="{ background: selectedProviderId === p.id ? 'var(--n-color-embedded)' : 'transparent' }">
          <span style="font-size:18px;width:24px;text-align:center">{{ providerIcon(p.type) }}</span>
          <div style="flex:1;min-width:0">
            <div style="font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ p.name }}</div>
            <div style="font-size:11px;color:#8b8f97">{{ t('ai.models', { count: p.models?.length || 0 }) }}</div>
          </div>
          <div v-if="p.is_active" style="width:8px;height:8px;border-radius:50%;background:#0ecb81;flex-shrink:0"></div>
        </div>
      </n-spin>
    </div>

    <!-- 右侧详情 -->
    <div style="flex:1;overflow-y:auto;padding:16px 20px">
      <n-empty v-if="!selectedProviderId" :description="t('ai.select_hint')" style="margin-top:80px" />

      <template v-if="selectedProviderId">
        <!-- 头部 -->
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:24px">{{ providerIcon(selectedProvider?.type || form.type) }}</span>
            <div>
              <div style="font-size:16px;font-weight:600">{{ selectedProvider?.name || form.name || t('ai.new_provider') }}</div>
              <div style="font-size:12px;color:#8b8f97">{{ form.type === 'ollama' ? t('ai.local_model') : t('ai.openai_compatible') }}</div>
            </div>
            <n-tag v-if="selectedProvider?.is_active" :bordered="false" type="success" size="tiny">{{ t('ai.activated') }}</n-tag>
          </div>
          <div style="display:flex;gap:6px">
            <n-button v-if="selectedProvider && !selectedProvider.is_active" size="tiny" secondary @click="activateProvider(selectedProvider.id)">{{ t('ai.activate') }}</n-button>
            <n-popconfirm v-if="selectedProvider && selectedProviderId !== 'new'" @positive-click="deleteProvider(selectedProvider.id)">
              <template #trigger><n-button size="tiny" quaternary type="error">{{ t('ai.delete') }}</n-button></template>
              {{ t('ai.confirm_delete') }}
            </n-popconfirm>
          </div>
        </div>

        <!-- 配置表单 -->
        <div style="display:grid;gap:16px;max-width:480px">
          <div>
            <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">{{ t('ai.base_url') }}</div>
            <n-input v-model:value="form.base_url" size="small" placeholder="https://api.openai.com/v1" />
          </div>
          <div>
            <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">{{ t('ai.api_key') }}</div>
            <n-input v-model:value="form.api_key" size="small" type="password" :placeholder="selectedProviderId === 'new' ? 'sk-...' : t('ai.keep_empty')" />
          </div>
          <div>
            <n-button @click="testConnection" :loading="testing" size="small" secondary>{{ t('ai.test_connection') }}</n-button>
          </div>

          <!-- 模型列表 -->
          <div v-if="form.models.length > 0">
            <div style="font-size:12px;color:#8b8f97;margin-bottom:8px">{{ t('ai.model_list') }}</div>
            <div v-for="m in form.models" :key="m"
              style="display:flex;align-items:center;justify-content:space-between;padding:6px 8px;border-radius:4px;margin-bottom:2px"
              :style="{ background: form.enabled_models.includes(m) ? 'var(--n-color-embedded)' : 'transparent' }">
              <div style="display:flex;align-items:center;gap:8px">
                <n-switch :value="form.enabled_models.includes(m)" size="small" @update:value="() => toggleModel(m)" />
                <span :style="{ fontWeight: form.selected_model === m ? 600 : 400, fontSize: '13px' }">{{ m }}</span>
              </div>
              <n-tag v-if="form.selected_model === m" :bordered="false" size="tiny" type="primary">{{ t('ai.in_use') }}</n-tag>
            </div>
          </div>

          <div style="margin-top:8px;display:flex;gap:8px">
            <n-button type="primary" size="small" @click="saveProvider" :loading="saving">{{ t('ai.save') }}</n-button>
            <n-button v-if="selectedProviderId === 'new'" size="small" quaternary @click="selectedProviderId = null">{{ t('ai.cancel') }}</n-button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>