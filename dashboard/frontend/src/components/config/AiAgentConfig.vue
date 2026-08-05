<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()

const providers = ref<any[]>([])
const activeProvider = ref<any>(null)
const loading = ref(false)
const selectedProviderId = ref<string | null>(null)
const testing = ref(false)
const editing = ref(false)

const formData = ref({
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

const hasChanges = computed(() => {
  const p = selectedProvider.value
  if (!p) return false
  return formData.value.name !== p.name ||
    formData.value.type !== p.type ||
    formData.value.base_url !== p.base_url ||
    formData.value.selected_model !== p.selected_model
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
  editing.value = false
  const p = providers.value.find(x => x.id === id)
  if (!p) return
  formData.value = {
    name: p.name,
    type: p.type,
    api_key: p.api_key || '',
    base_url: p.base_url,
    models: p.models || [],
    enabled_models: p.enabled_models || [],
    selected_model: p.selected_model || '',
  }
  if (p.models?.length === 0) {
    testConnection(true)
  }
}

function addProvider() {
  // Create a new temp provider
  selectedProviderId.value = 'new'
  editing.value = true
  formData.value = {
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
  if (!formData.value.name) {
    message.warning('请输入 Provider 名称')
    return
  }
  try {
    const body = {
      name: formData.value.name,
      type: formData.value.type,
      api_key: formData.value.api_key,
      base_url: formData.value.base_url,
      models: formData.value.models,
      enabled_models: formData.value.enabled_models,
      selected_model: formData.value.selected_model,
    }
    if (selectedProviderId.value === 'new') {
      const res = await fetch('/api/llm/providers', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await res.json()
      if (d.success) {
        message.success('已添加')
        selectedProviderId.value = d.data.id
      }
    } else {
      const res = await fetch(`/api/llm/providers/${selectedProviderId.value}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await res.json()
      if (d.success) message.success('已保存')
    }
    editing.value = false
    await loadProviders()
  } catch (e: any) {
    message.error('保存失败: ' + (e.message || ''))
  }
}

async function deleteProvider(id: string) {
  try {
    const res = await fetch(`/api/llm/providers/${id}`, { method: 'DELETE' })
    const d = await res.json()
    if (d.success) {
      message.success('已删除')
      if (selectedProviderId.value === id) selectedProviderId.value = null
      await loadProviders()
    }
  } catch { message.error('删除失败') }
}

async function activateProvider(id: string) {
  try {
    const res = await fetch(`/api/llm/providers/${id}/activate`, { method: 'POST' })
    const d = await res.json()
    if (d.success) { message.success('已设为激活'); await loadProviders() }
  } catch { message.error('激活失败') }
}

function toggleModel(model: string) {
  const idx = formData.value.enabled_models.indexOf(model)
  if (idx >= 0) {
    formData.value.enabled_models.splice(idx, 1)
    if (formData.value.selected_model === model) {
      formData.value.selected_model = formData.value.enabled_models[0] || ''
    }
  } else {
    formData.value.enabled_models.push(model)
    if (!formData.value.selected_model) formData.value.selected_model = model
  }
}

async function testConnection(silent = false) {
  if (!formData.value.base_url) { if (!silent) message.warning('请先填写 Base URL'); return }
  if (formData.value.type !== 'ollama' && !formData.value.api_key) { if (!silent) message.warning('请先填写 API Key'); return }
  testing.value = true
  try {
    let id = selectedProviderId.value
    if (id === 'new' || !id) {
      const saveRes = await fetch('/api/llm/providers', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: formData.value.name || 'temp', type: formData.value.type, api_key: formData.value.api_key, base_url: formData.value.base_url }),
      })
      const d = await saveRes.json()
      if (!d.success) { if (!silent) message.error('保存失败'); return }
      id = d.data.id; selectedProviderId.value = id
    } else {
      await fetch(`/api/llm/providers/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ api_key: formData.value.api_key, base_url: formData.value.base_url }) })
    }
    const res = await fetch(`/api/llm/providers/${id}/test`, { method: 'POST' })
    const d = await res.json()
    if (d.success && d.data?.models?.length) {
      formData.value.models = d.data.models
      formData.value.enabled_models = [...d.data.models]
      formData.value.selected_model = d.data.models[0]
      if (!silent) message.success(`测试成功！发现 ${d.data.models.length} 个模型`)
    } else if (d.success && d.data?.warning) {
      if (!silent) message.warning(d.data.warning)
    } else if (d.success) {
      if (!silent) message.success('连接成功')
    }
  } catch (e: any) { if (!silent) message.error('测试失败: ' + (e.message || '')) }
  finally { testing.value = false }
}

function providerIcon(type: string): string { return type === 'ollama' ? '🦙' : '🤖' }

onMounted(loadProviders)
</script>

<template>
  <div style="display:flex;gap:12px;height:calc(100vh - 280px);min-height:400px">
    <!-- 左侧 Provider 列表 -->
    <div style="width:220px;flex-shrink:0;overflow-y:auto">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <span style="font-weight:600;font-size:13px">Provider</span>
        <n-button size="tiny" quaternary circle @click="addProvider">+</n-button>
      </div>
      <n-spin :show="loading" size="small">
        <n-empty v-if="!loading && providers.length === 0" description="暂无" size="small" />
        <div v-for="p in providers" :key="p.id"
          @click="selectProvider(p.id)"
          style="display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:6px;cursor:pointer;margin-bottom:2px"
          :style="{
            background: selectedProviderId === p.id ? 'var(--n-color-embedded)' : 'transparent',
          }">
          <span style="font-size:18px">{{ providerIcon(p.type) }}</span>
          <div style="flex:1;min-width:0">
            <div style="font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ p.name }}</div>
            <div style="font-size:11px;color:#8b8f97">{{ p.models?.length || 0 }} 模型</div>
          </div>
          <n-tag v-if="p.is_active" :bordered="false" type="success" size="tiny">激活</n-tag>
        </div>
      </n-spin>
    </div>

    <!-- 右侧 Provider 详情 -->
    <div style="flex:1;overflow-y:auto">
      <n-empty v-if="!selectedProviderId" description="请选择一个 Provider" style="margin-top:60px" />

      <div v-else-if="selectedProviderId === 'new'" style="padding:0 4px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
          <span style="font-weight:600;font-size:16px">添加 Provider</span>
        </div>
        <n-form label-placement="left" label-width="100px" size="small">
          <n-form-item label="名称"><n-input v-model:value="formData.name" placeholder="如: DeepSeek, OpenAI" /></n-form-item>
          <n-form-item label="类型">
            <n-select v-model:value="formData.type" :options="[{ label: 'OpenAI 兼容', value: 'openai' }, { label: 'Ollama（本地）', value: 'ollama' }]" />
          </n-form-item>
          <n-form-item label="API Key"><n-input v-model:value="formData.api_key" type="password" placeholder="sk-..." /></n-form-item>
          <n-form-item label="API 地址"><n-input v-model:value="formData.base_url" placeholder="https://api.openai.com/v1" /></n-form-item>
          <n-form-item label=" ">
            <n-button @click="testConnection()" :loading="testing" secondary size="small">测试连接</n-button>
          </n-form-item>
          <div v-if="formData.models.length > 0" style="margin-top:8px">
            <div style="font-size:12px;color:#8b8f97;margin-bottom:8px">可用模型（勾选启用）</div>
            <div v-for="m in formData.models" :key="m" style="display:flex;align-items:center;justify-content:space-between;padding:3px 0">
              <n-checkbox :checked="formData.enabled_models.includes(m)" @update:checked="() => toggleModel(m)">
                <span :style="{ fontWeight: formData.selected_model === m ? 600 : 400 }">{{ m }}</span>
              </n-checkbox>
              <n-button v-if="formData.enabled_models.includes(m) && formData.selected_model !== m" size="tiny" quaternary @click="formData.selected_model = m">设为当前</n-button>
            </div>
          </div>
          <div style="margin-top:16px">
            <n-button type="primary" size="small" @click="saveProvider">保存</n-button>
          </div>
        </n-form>
      </div>

      <div v-else-if="selectedProvider" style="padding:0 4px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:22px">{{ providerIcon(selectedProvider.type) }}</span>
            <span style="font-weight:600;font-size:16px">{{ selectedProvider.name }}</span>
            <n-tag v-if="selectedProvider.is_active" :bordered="false" type="success" size="tiny">已激活</n-tag>
          </div>
          <div style="display:flex;gap:6px">
            <n-button v-if="!selectedProvider.is_active" size="tiny" type="primary" @click="activateProvider(selectedProvider.id)">激活</n-button>
            <n-button size="tiny" quaternary @click="editing = !editing">{{ editing ? '取消' : '编辑' }}</n-button>
            <n-popconfirm @positive-click="deleteProvider(selectedProvider.id)">
              <template #trigger><n-button size="tiny" quaternary type="error">删除</n-button></template>
              确认删除？
            </n-popconfirm>
          </div>
        </div>

        <!-- 状态卡片 -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px">
          <div style="padding:10px 12px;border-radius:6px;background:var(--n-color-embedded)">
            <div style="font-size:11px;color:#8b8f97">模型</div>
            <div style="font-size:14px;font-weight:600;margin-top:2px">{{ selectedProvider.models?.length || 0 }} 个可用 · {{ selectedProvider.enabled_models?.length || 0 }} 个启用</div>
          </div>
          <div style="padding:10px 12px;border-radius:6px;background:var(--n-color-embedded)">
            <div style="font-size:11px;color:#8b8f97">当前模型</div>
            <div style="font-size:14px;font-weight:600;margin-top:2px">{{ selectedProvider.selected_model || '未设置' }}</div>
          </div>
        </div>

        <!-- 编辑模式 -->
        <div v-if="editing">
          <n-form label-placement="left" label-width="100px" size="small">
            <n-form-item label="名称"><n-input v-model:value="formData.name" /></n-form-item>
            <n-form-item label="类型">
              <n-select v-model:value="formData.type" :options="[{ label: 'OpenAI 兼容', value: 'openai' }, { label: 'Ollama（本地）', value: 'ollama' }]" />
            </n-form-item>
            <n-form-item label="API Key"><n-input v-model:value="formData.api_key" type="password" placeholder="留空则不修改" /></n-form-item>
            <n-form-item label="API 地址"><n-input v-model:value="formData.base_url" /></n-form-item>
            <n-form-item label=" ">
              <n-button @click="testConnection()" :loading="testing" secondary size="small">测试连接并获取模型</n-button>
            </n-form-item>
            <div v-if="formData.models.length > 0" style="margin-top:8px">
              <div style="font-size:12px;color:#8b8f97;margin-bottom:8px">可用模型</div>
              <div v-for="m in formData.models" :key="m" style="display:flex;align-items:center;justify-content:space-between;padding:3px 0">
                <n-checkbox :checked="formData.enabled_models.includes(m)" @update:checked="() => toggleModel(m)">
                  <span :style="{ fontWeight: formData.selected_model === m ? 600 : 400 }">{{ m }}</span>
                </n-checkbox>
                <n-button v-if="formData.enabled_models.includes(m) && formData.selected_model !== m" size="tiny" quaternary @click="formData.selected_model = m">设为当前</n-button>
              </div>
            </div>
            <div style="margin-top:16px">
              <n-button type="primary" size="small" @click="saveProvider">保存</n-button>
            </div>
          </n-form>
        </div>

        <!-- 查看模式 -->
        <div v-else style="font-size:13px">
          <div style="display:grid;grid-template-columns:100px 1fr;gap:6px;padding:6px 0">
            <span style="color:#8b8f97">API 地址</span>
            <span>{{ selectedProvider.base_url }}</span>
          </div>
          <div style="display:grid;grid-template-columns:100px 1fr;gap:6px;padding:6px 0">
            <span style="color:#8b8f97">API Key</span>
            <span>{{ selectedProvider.api_key || '未设置' }}</span>
          </div>
          <div style="display:grid;grid-template-columns:100px 1fr;gap:6px;padding:6px 0">
            <span style="color:#8b8f97">已启用模型</span>
            <div>
              <n-tag v-for="m in selectedProvider.enabled_models" :key="m" :bordered="false" size="tiny" style="margin:2px">
                {{ m }}
              </n-tag>
              <span v-if="!selectedProvider.enabled_models?.length" style="color:#8b8f97">无</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>