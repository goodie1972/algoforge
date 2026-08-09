<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'
import type { FormInst } from 'naive-ui'

const { t } = useI18n()
const message = useMessage()

const providers = ref<any[]>([])
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const showModal = ref(false)
const editingId = ref<string | null>(null)
const formRef = ref<FormInst | null>(null)

const form = ref({
  name: '',
  type: 'openai',
  api_key: '',
  base_url: 'https://api.openai.com/v1',
  models: [] as string[],
  enabled_models: [] as string[],
  selected_model: '',
})

const isEditing = computed(() => editingId.value !== null && editingId.value !== 'new')

async function loadProviders() {
  loading.value = true
  try {
    const res = await fetch('/api/llm/providers')
    const d = await res.json()
    if (d.success) providers.value = d.data
  } catch (e) {
    console.error('加载失败', e)
  } finally {
    loading.value = false
  }
}

function openNew() {
  editingId.value = 'new'
  form.value = { name: '', type: 'openai', api_key: '', base_url: 'https://api.openai.com/v1', models: [], enabled_models: [], selected_model: '' }
  showModal.value = true
}

function openEdit(id: string) {
  const p = providers.value.find(x => x.id === id)
  if (!p) return
  editingId.value = id
  form.value = {
    name: p.name, type: p.type, api_key: p.api_key || '',
    base_url: p.base_url, models: p.models || [],
    enabled_models: p.enabled_models || [],
    selected_model: p.selected_model || '',
  }
  showModal.value = true
}

async function saveProvider() {
  if (!form.value.name) { message.warning(t('ai.name_required')); return }
  saving.value = true
  try {
    const body = { name: form.value.name, type: form.value.type, api_key: form.value.api_key, base_url: form.value.base_url, models: form.value.models, enabled_models: form.value.enabled_models, selected_model: form.value.selected_model }
    if (editingId.value === 'new') {
      const res = await fetch('/api/llm/providers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const d = await res.json()
      if (d.success) { message.success(t('ai.add')); editingId.value = d.data.id }
    } else {
      const res = await fetch(`/api/llm/providers/${editingId.value}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const d = await res.json()
      if (d.success) message.success(t('ai.saved'))
    }
    await loadProviders()
    showModal.value = false
  } catch (e: any) { message.error(t('ai.save_failed', { error: e.message || '' })) }
  finally { saving.value = false }
}

async function deleteProvider(id: string) {
  try {
    const res = await fetch(`/api/llm/providers/${id}`, { method: 'DELETE' })
    const d = await res.json()
    if (d.success) { message.success(t('ai.deleted')); await loadProviders() }
  } catch { message.error(t('ai.delete_failed')) }
}

async function activateProvider(id: string) {
  try {
    const res = await fetch(`/api/llm/providers/${id}/activate`, { method: 'POST' })
    const d = await res.json()
    if (d.success) { message.success(t('ai.activated')); await loadProviders() }
  } catch { message.error(t('ai.activate_failed')) }
}

async function testConnection() {
  if (!form.value.base_url) { message.warning(t('ai.api_url_required')); return }
  if (form.value.type !== 'ollama' && !form.value.api_key) { message.warning(t('ai.api_key_required')); return }
  testing.value = true
  try {
    let id = editingId.value
    if (id === 'new' || !id) {
      const r = await fetch('/api/llm/providers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: form.value.name || 'temp', type: form.value.type, api_key: form.value.api_key, base_url: form.value.base_url }) })
      const d = await r.json()
      if (!d.success) { message.error(t('ai.save_failed')); return }
      id = d.data.id; editingId.value = id
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
  <div>
    <n-spin :show="loading" size="small">
      <div v-if="!loading && providers.length === 0" style="text-align:center;padding:60px 0;color:#8b8f97">
        {{ t('ai.no_providers') }}
      </div>

      <!-- 卡片网格 -->
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;padding:4px">
        <div v-for="p in providers" :key="p.id"
          style="border:1px solid var(--n-border-color);border-radius:10px;padding:16px;position:relative;transition:box-shadow 0.2s;background:var(--n-color)"
          :style="{ boxShadow: p.is_active ? '0 0 0 2px #0ecb81' : 'none' }">
          <!-- 顶部：图标 + 名称 + 开关 -->
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
            <div style="display:flex;align-items:center;gap:8px">
              <span style="font-size:20px;width:24px;text-align:center">{{ providerIcon(p.type) }}</span>
              <span style="font-weight:600;font-size:14px">{{ p.name }}</span>
            </div>
            <n-switch :value="p.is_active" size="small" @update:value="() => activateProvider(p.id)"
              :round="true" />
          </div>
          <!-- 模型名 -->
          <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">{{ p.selected_model || (p.models?.[0] || '') }}</div>
          <div style="font-size:11px;color:#666;margin-bottom:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ p.base_url }}</div>
          <!-- 底部按钮 -->
          <div style="display:flex;gap:6px">
            <n-button size="tiny" quaternary @click="openEdit(p.id)">{{ t('ai.configure') }}</n-button>
            <n-popconfirm @positive-click="deleteProvider(p.id)">
              <template #trigger><n-button size="tiny" quaternary type="error">{{ t('ai.delete') }}</n-button></template>
              {{ t('ai.confirm_delete') }}
            </n-popconfirm>
          </div>
        </div>

        <!-- 空白卡片：添加新 Provider -->
        <div @click="openNew"
          style="border:1px dashed var(--n-border-color);border-radius:10px;padding:16px;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:pointer;min-height:140px;transition:all 0.2s;background:var(--n-color)"
          @mouseover="(e:any) => e.currentTarget.style.borderColor='#0ecb81'"
          @mouseout="(e:any) => e.currentTarget.style.borderColor='var(--n-border-color)'">
          <span style="font-size:28px;color:#8b8f97;margin-bottom:6px">+</span>
          <span style="font-size:13px;color:#8b8f97">{{ t('ai.add_provider') }}</span>
        </div>
      </div>
    </n-spin>

    <!-- 编辑 Modal -->
    <n-modal v-model:show="showModal" :mask-closable="false" preset="card" style="max-width:520px" :title="editingId === 'new' ? t('ai.add_provider') : t('ai.configure')">
      <n-form ref="formRef" :model="form" label-placement="left" label-width="100px" style="margin-top:12px">
        <n-form-item :label="t('ai.name')" path="name">
          <n-input v-model:value="form.name" size="small" :placeholder="t('ai.name_placeholder')" />
        </n-form-item>
        <n-form-item :label="t('ai.base_url')" path="base_url">
          <n-input v-model:value="form.base_url" size="small" placeholder="https://api.openai.com/v1" />
        </n-form-item>
        <n-form-item :label="t('ai.api_key')" path="api_key">
          <n-input v-model:value="form.api_key" size="small" type="password" :placeholder="isEditing ? t('ai.keep_empty') : 'sk-...'" />
        </n-form-item>
        <n-form-item :label="t('ai.model')" path="selected_model">
          <n-input v-model:value="form.selected_model" size="small" placeholder="gpt-4o-mini" />
        </n-form-item>
        <n-form-item :label="t('ai.type')" path="type">
          <n-select v-model:value="form.type" size="small" :options="[
            { label: 'OpenAI 兼容', value: 'openai' },
            { label: 'Ollama（本地）', value: 'ollama' },
          ]" />
        </n-form-item>
      </n-form>

      <template #footer>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <n-button @click="testConnection" :loading="testing" size="small" secondary>{{ t('ai.test_connection') }}</n-button>
          <div style="display:flex;gap:8px">
            <n-button size="small" quaternary @click="showModal = false">{{ t('ai.cancel') }}</n-button>
            <n-button type="primary" size="small" @click="saveProvider" :loading="saving">{{ t('ai.save') }}</n-button>
          </div>
        </div>
      </template>
    </n-modal>
  </div>
</template>