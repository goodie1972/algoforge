<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'

const { t } = useI18n()
const message = useMessage()

const providers = ref<any[]>([])
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const editingId = ref<string | null>(null)  // null=无编辑, 'new'=新增, 其他=编辑某卡片
const showModal = ref(false)  // 编辑 Modal
const showKey = ref(false)

const form = ref({
  name: '',
  type: 'openai',
  api_key: '',
  base_url: 'https://api.openai.com/v1',
  models: [] as string[],
  enabled_models: [] as string[],
  selected_model: '',
})

const isEditingExisting = computed(() => editingId.value !== null && editingId.value !== 'new')

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
  showKey.value = false
  showModal.value = true
  form.value = { name: '', type: 'openai', api_key: '', base_url: 'https://api.openai.com/v1', models: [], enabled_models: [], selected_model: '' }
}

function openEdit(id: string) {
  const p = providers.value.find(x => x.id === id)
  if (!p) return
  editingId.value = id
  showKey.value = false
  showModal.value = true
  form.value = {
    name: p.name, type: p.type, api_key: p.api_key || '',
    base_url: p.base_url, models: p.models || [],
    enabled_models: p.enabled_models || [],
    selected_model: p.selected_model || '',
  }
}

function cancelEdit() {
  showModal.value = false
  editingId.value = null
  showKey.value = false
  testing.value = false
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
    showModal.value = false  // 关闭 Modal
    editingId.value = null
    showKey.value = false
  } catch (e: any) { message.error(t('ai.save_failed', { error: e.message || '' })) }
  finally { saving.value = false }
}

async function deleteProvider(id: string) {
  try {
    const res = await fetch(`/api/llm/providers/${id}`, { method: 'DELETE' })
    const d = await res.json()
    if (d.success) { message.success(t('ai.deleted')); if (editingId.value === id) editingId.value = null; await loadProviders() }
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

onMounted(loadProviders)

// ── 人设 ──
const personaName = ref('')
const personaRole = ref('')
const personaStyle = ref('')
const personaLimits = ref('')

async function loadPersona() {
  try {
    const r = await fetch('/api/ai/persona')
    const d = await r.json()
    if (d.current) {
      personaName.value = d.current.name || ''
      personaRole.value = d.current.role || ''
      personaStyle.value = d.current.style || ''
      personaLimits.value = d.current.limits || ''
    }
  } catch (e) { /* ignore */ }
}
async function savePersona() {
  await fetch('/api/ai/persona', {
    method: 'PUT',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ name: personaName.value, role: personaRole.value, style: personaStyle.value, limits: personaLimits.value, language: 'zh-CN', save: true }),
  })
  message.success('人设已保存')
}

// ── 技能 ──
const skills = ref<any[]>([])
async function loadSkills() {
  try {
    const r = await fetch('/api/ai/skills')
    const d = await r.json()
    skills.value = d.skills || []
  } catch (e) { /* ignore */ }
}

onMounted(() => { loadPersona(); loadSkills() })
</script>

<template>
  <div>
    <n-spin :show="loading" size="small">
      <div v-if="!loading && providers.length === 0" style="text-align:center;padding:60px 0;color:#8b8f97">
        {{ t('ai.no_providers') }}
      </div>

      <!-- 卡片网格 -->
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px;padding:4px">
        <div v-for="p in providers" :key="p.id">
          <div @click="openEdit(p.id)"
            style="border:2px solid var(--n-border-color);border-radius:10px;padding:16px;cursor:pointer;transition:border-color 0.2s;background:transparent;min-height:120px;display:flex;flex-direction:column"
            :style="{ borderColor: p.is_active ? '#0ecb81' : 'var(--n-border-color)' }">
            <!-- 顶部：名称 + 开关 -->
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
              <span style="font-weight:600;font-size:15px">{{ p.name }}</span>
              <div @click.stop>
                <n-switch :value="p.is_active" size="small" @update:value="() => activateProvider(p.id)" :round="true" />
              </div>
            </div>
            <!-- 模型 -->
            <div style="font-size:13px;color:#333;margin-bottom:4px">{{ p.selected_model || (p.models?.[0] || '') }}</div>
            <!-- URL -->
            <div style="font-size:11px;color:#8b8f97;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:8px">{{ p.base_url }}</div>
            <!-- 底部 -->
            <div style="margin-top:auto;display:flex;justify-content:space-between;align-items:center">
              <n-tag v-if="p.is_active" :bordered="false" size="tiny" type="success">{{ t('ai.activated') }}</n-tag>
              <div v-else @click.stop>
                <n-popconfirm @positive-click="deleteProvider(p.id)">
                  <template #trigger><n-button size="tiny" quaternary type="error">✕</n-button></template>
                  {{ t('ai.confirm_delete') }}
                </n-popconfirm>
              </div>
            </div>
          </div>
        </div>

        <!-- 空白卡片 -->
        <div v-if="!showModal" @click="openNew"
          style="border:2px dashed var(--n-border-color);border-radius:10px;padding:16px;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:pointer;min-height:120px;transition:border-color 0.2s;background:transparent"
          @mouseover="(e:any) => e.currentTarget.style.borderColor='#8b8f97'"
          @mouseout="(e:any) => e.currentTarget.style.borderColor='var(--n-border-color)'">
          <span style="font-size:26px;color:#8b8f97;margin-bottom:4px">+</span>
          <span style="font-size:13px;color:#8b8f97">{{ t('ai.add_provider') }}</span>
        </div>
      </div>
    </n-spin>

    <!-- 编辑 Modal → 弹出放大 -->
    <n-modal v-model:show="showModal" :mask-closable="false" preset="card" style="max-width:600px" :title="editingId === 'new' ? t('ai.add_provider') : t('ai.configure')">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px">
        <div>
          <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">{{ t('ai.name') }}</div>
          <n-input v-model:value="form.name" size="small" :placeholder="t('ai.name_placeholder')" />
        </div>
        <div>
          <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">{{ t('ai.type') }}</div>
          <n-select v-model:value="form.type" size="small" :options="[
            { label: 'OpenAI 兼容', value: 'openai' },
            { label: 'Ollama（本地）', value: 'ollama' },
          ]" />
        </div>
        <div style="grid-column:span 2">
          <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">{{ t('ai.base_url') }}</div>
          <n-input v-model:value="form.base_url" size="small" placeholder="https://api.openai.com/v1" />
        </div>
        <div style="grid-column:span 2">
          <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">{{ t('ai.api_key') }}</div>
          <n-input v-model:value="form.api_key" size="small" :type="showKey ? 'text' : 'password'" :placeholder="isEditingExisting ? t('ai.keep_empty') : 'sk-...'">
            <template #suffix>
              <span @click="showKey = !showKey" style="cursor:pointer;color:#8b8f97;font-size:16px" :title="showKey ? '隐藏' : '显示'">
                {{ showKey ? '👁️' : '🙈' }}
              </span>
            </template>
          </n-input>
        </div>
        <div style="grid-column:span 2">
          <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">{{ t('ai.model') }}</div>
          <n-select v-model:value="form.selected_model" size="small" filterable allow-create :placeholder="t('ai.model_placeholder')"
            :options="form.models.map(m => ({ label: m, value: m }))" />
        </div>
      </div>

      <template #footer>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <n-button @click="testConnection" :loading="testing" size="small" secondary>{{ t('ai.test_connection') }}</n-button>
          <div style="display:flex;gap:8px">
            <n-button size="small" quaternary @click="cancelEdit">{{ t('ai.cancel') }}</n-button>
            <n-button type="primary" size="small" @click="saveProvider" :loading="saving">{{ t('ai.save') }}</n-button>
          </div>
        </div>
      </template>
    </n-modal>

    <!-- ── 人设配置 ── -->
    <n-divider />
    <n-h3>AI 人设</n-h3>
    <n-space vertical>
      <n-input-group>
        <n-input-group-label>人设名</n-input-group-label>
        <n-input v-model:value="personaName" placeholder="金探" style="flex:1" />
      </n-input-group>
      <n-input
        v-model:value="personaRole"
        type="textarea"
        placeholder="角色描述（如：专业的 XAUUSD 黄金量化交易分析师）"
        :rows="2"
      />
      <n-input
        v-model:value="personaStyle"
        type="textarea"
        placeholder="回答风格"
        :rows="2"
      />
      <n-input
        v-model:value="personaLimits"
        type="textarea"
        placeholder="限制（如：不直接执行交易）"
        :rows="2"
      />
      <n-button size="small" @click="savePersona">保存人设</n-button>
    </n-space>

    <!-- ── 已加载技能列表 ── -->
    <n-divider />
    <n-h3>已加载技能 ({{ skills.length }})</n-h3>
    <n-space vertical v-if="skills.length > 0">
      <n-card v-for="s in skills" :key="s.name" size="small" :title="s.name">
        {{ s.description }}
      </n-card>
    </n-space>
    <n-empty v-else description="暂无技能" />
  </div>
</template>