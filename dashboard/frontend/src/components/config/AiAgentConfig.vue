<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'

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
  if (!form.value.name) { message.warning('请输入名称'); return }
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
      if (d.success) { message.success('已添加'); selectedProviderId.value = d.data.id }
    } else {
      const res = await fetch(`/api/llm/providers/${selectedProviderId.value}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const d = await res.json()
      if (d.success) message.success('已保存')
    }
    await loadProviders()
  } catch (e: any) { message.error('保存失败: ' + (e.message || '')) }
  finally { saving.value = false }
}

async function deleteProvider(id: string) {
  try {
    const res = await fetch(`/api/llm/providers/${id}`, { method: 'DELETE' })
    const d = await res.json()
    if (d.success) { message.success('已删除'); if (selectedProviderId.value === id) selectedProviderId.value = null; await loadProviders() }
  } catch { message.error('删除失败') }
}

async function activateProvider(id: string) {
  try {
    const res = await fetch(`/api/llm/providers/${id}/activate`, { method: 'POST' })
    const d = await res.json()
    if (d.success) { message.success('已激活'); await loadProviders() }
  } catch { message.error('激活失败') }
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
  if (!form.value.base_url) { message.warning('请先填写 API 地址'); return }
  if (form.value.type !== 'ollama' && !form.value.api_key) { message.warning('请先填写 API Key'); return }
  testing.value = true
  try {
    let id = selectedProviderId.value
    if (id === 'new' || !id) {
      const r = await fetch('/api/llm/providers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: form.value.name || 'temp', type: form.value.type, api_key: form.value.api_key, base_url: form.value.base_url }) })
      const d = await r.json()
      if (!d.success) { message.error('保存失败'); return }
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
      message.success(`测试成功！发现 ${d.data.models.length} 个模型`)
    } else if (d.success) {
      message.success('连接成功')
    } else {
      message.error('测试失败')
    }
  } catch (e: any) { message.error('测试失败: ' + (e.message || '')) }
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
        <span style="font-weight:600;font-size:13px">模型服务商</span>
        <n-button size="tiny" quaternary circle @click="addProvider" style="font-size:16px;line-height:1">+</n-button>
      </div>
      <n-spin :show="loading" size="small">
        <n-empty v-if="!loading && providers.length === 0" description="暂无" size="small" />
        <div v-for="p in providers" :key="p.id" @click="selectProvider(p.id)"
          style="display:flex;align-items:center;gap:8px;padding:8px;border-radius:6px;cursor:pointer;margin-bottom:2px;transition:background 0.2s"
          :style="{ background: selectedProviderId === p.id ? 'var(--n-color-embedded)' : 'transparent' }">
          <span style="font-size:18px;width:24px;text-align:center">{{ providerIcon(p.type) }}</span>
          <div style="flex:1;min-width:0">
            <div style="font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ p.name }}</div>
            <div style="font-size:11px;color:#8b8f97">{{ p.models?.length || 0 }} 模型</div>
          </div>
          <div v-if="p.is_active" style="width:8px;height:8px;border-radius:50%;background:#0ecb81;flex-shrink:0"></div>
        </div>
      </n-spin>
    </div>

    <!-- 右侧详情 -->
    <div style="flex:1;overflow-y:auto;padding:16px 20px">
      <n-empty v-if="!selectedProviderId" description="选择左侧模型服务商开始配置" style="margin-top:80px" />

      <template v-if="selectedProviderId">
        <!-- 头部 -->
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:24px">{{ providerIcon(selectedProvider?.type || form.type) }}</span>
            <div>
              <div style="font-size:16px;font-weight:600">{{ selectedProvider?.name || form.name || '新服务商' }}</div>
              <div style="font-size:12px;color:#8b8f97">{{ form.type === 'ollama' ? '本地模型' : 'OpenAI 兼容' }}</div>
            </div>
            <n-tag v-if="selectedProvider?.is_active" :bordered="false" type="success" size="tiny">已激活</n-tag>
          </div>
          <div style="display:flex;gap:6px">
            <n-button v-if="selectedProvider && !selectedProvider.is_active" size="tiny" secondary @click="activateProvider(selectedProvider.id)">激活</n-button>
            <n-popconfirm v-if="selectedProvider && selectedProviderId !== 'new'" @positive-click="deleteProvider(selectedProvider.id)">
              <template #trigger><n-button size="tiny" quaternary type="error">删除</n-button></template>
              确认删除此服务商？
            </n-popconfirm>
          </div>
        </div>

        <!-- 配置表单 -->
        <div style="display:grid;gap:16px;max-width:480px">
          <div>
            <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">API 地址</div>
            <n-input v-model:value="form.base_url" size="small" placeholder="https://api.openai.com/v1" />
          </div>
          <div>
            <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">API Key</div>
            <n-input v-model:value="form.api_key" size="small" type="password" :placeholder="selectedProviderId === 'new' ? 'sk-...' : '留空则不修改'" />
          </div>
          <div>
            <n-button @click="testConnection" :loading="testing" size="small" secondary>测试连接</n-button>
          </div>

          <!-- 模型列表 -->
          <div v-if="form.models.length > 0">
            <div style="font-size:12px;color:#8b8f97;margin-bottom:8px">模型列表</div>
            <div v-for="m in form.models" :key="m"
              style="display:flex;align-items:center;justify-content:space-between;padding:6px 8px;border-radius:4px;margin-bottom:2px"
              :style="{ background: form.enabled_models.includes(m) ? 'var(--n-color-embedded)' : 'transparent' }">
              <div style="display:flex;align-items:center;gap:8px">
                <n-switch :value="form.enabled_models.includes(m)" size="small" @update:value="() => toggleModel(m)" />
                <span :style="{ fontWeight: form.selected_model === m ? 600 : 400, fontSize: '13px' }">{{ m }}</span>
              </div>
              <n-tag v-if="form.selected_model === m" :bordered="false" size="tiny" type="primary">使用中</n-tag>
            </div>
          </div>

          <div style="margin-top:8px;display:flex;gap:8px">
            <n-button type="primary" size="small" @click="saveProvider" :loading="saving">保存</n-button>
            <n-button v-if="selectedProviderId === 'new'" size="small" quaternary @click="selectedProviderId = null">取消</n-button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>