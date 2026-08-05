<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()

const providers = ref<any[]>([])
const activeProvider = ref<any>(null)
const loading = ref(false)
const showForm = ref(false)
const editing = ref(false)
const editId = ref('')
const formData = ref({
  name: '',
  type: 'openai',
  api_key: '',
  base_url: 'https://api.openai.com/v1',
  models: [] as string[],
  enabled_models: [] as string[],
  selected_model: '',
})
const testing = ref(false)
const testResult = ref<{models: string[]; warning?: string} | null>(null)

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

function openAdd() {
  editing.value = false
  editId.value = ''
  testResult.value = null
  formData.value = {
    name: '',
    type: 'openai',
    api_key: '',
    base_url: 'https://api.openai.com/v1',
    models: [],
    enabled_models: [],
    selected_model: '',
  }
  showForm.value = true
}

function openEdit(p: any) {
  editing.value = true
  editId.value = p.id
  testResult.value = null
  formData.value = {
    name: p.name,
    type: p.type,
    api_key: p.api_key?.startsWith('sk-') ? p.api_key : '',
    base_url: p.base_url,
    models: p.models || [],
    enabled_models: p.enabled_models || [],
    selected_model: p.selected_model || '',
  }
  showForm.value = true
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
    if (!formData.value.selected_model) {
      formData.value.selected_model = model
    }
  }
}

async function testConnection() {
  if (!formData.value.base_url) {
    message.warning('请先填写 Base URL')
    return
  }
  if (formData.value.type !== 'ollama' && !formData.value.api_key) {
    message.warning('请先填写 API Key')
    return
  }
  testing.value = true
  testResult.value = null
  try {
    let id = editId.value
    if (!id) {
      // 先临时保存 provider
      const saveRes = await fetch('/api/llm/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: formData.value.name || 'temp',
          type: formData.value.type,
          api_key: formData.value.api_key,
          base_url: formData.value.base_url,
        }),
      })
      const saveData = await saveRes.json()
      if (!saveData.success) { message.error('保存失败'); return }
      id = saveData.data.id
      editId.value = id
      editing.value = true
    } else {
      // 更新 API Key 和 Base URL
      await fetch(`/api/llm/providers/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_key: formData.value.api_key,
          base_url: formData.value.base_url,
        }),
      })
    }
    const res = await fetch(`/api/llm/providers/${id}/test`, { method: 'POST' })
    const d = await res.json()
    if (d.success) {
      testResult.value = d.data
      if (d.data.models?.length) {
        formData.value.models = d.data.models
        formData.value.enabled_models = [...d.data.models]
        formData.value.selected_model = d.data.models[0]
        message.success(`测试成功！发现 ${d.data.models.length} 个模型`)
      } else if (d.data.warning) {
        message.warning('连接成功，但获取模型列表失败: ' + d.data.warning)
      } else {
        message.success('连接成功！')
      }
    } else {
      message.error('测试失败: ' + (d.error || '未知错误'))
    }
  } catch (e: any) {
    message.error('测试失败: ' + (e.message || ''))
  } finally {
    testing.value = false
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
    if (editing.value) {
      const res = await fetch(`/api/llm/providers/${editId.value}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await res.json()
      if (d.success) message.success('已更新')
    } else {
      const res = await fetch('/api/llm/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await res.json()
      if (d.success) message.success('已添加')
    }
    showForm.value = false
    await loadProviders()
  } catch (e: any) {
    message.error('保存失败: ' + (e.message || ''))
  }
}

async function deleteProvider(id: string) {
  try {
    const res = await fetch(`/api/llm/providers/${id}`, { method: 'DELETE' })
    const d = await res.json()
    if (d.success) { message.success('已删除'); await loadProviders() }
  } catch { message.error('删除失败') }
}

async function activateProvider(id: string) {
  try {
    const res = await fetch(`/api/llm/providers/${id}/activate`, { method: 'POST' })
    const d = await res.json()
    if (d.success) { message.success('已设为激活'); await loadProviders() }
  } catch { message.error('激活失败') }
}

async function testProvider(id: string) {
  testing.value = true
  try {
    const res = await fetch(`/api/llm/providers/${id}/test`, { method: 'POST' })
    const d = await res.json()
    if (d.success) {
      const dt = d.data
      if (dt.models?.length) {
        message.success(`连接成功！发现 ${dt.models.length} 个模型`)
      } else if (dt.warning) {
        message.warning('连接成功: ' + dt.warning)
      } else {
        message.success('连接成功')
      }
      await loadProviders()
    }
  } catch { message.error('测试失败') }
  finally { testing.value = false }
}

function providerIcon(type: string): string {
  return type === 'ollama' ? '🦙' : '🤖'
}

onMounted(loadProviders)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <n-text depth="2">配置 LLM Provider 用于 AI 复盘分析</n-text>
      <n-button type="primary" size="small" @click="openAdd">+ 添加 Provider</n-button>
    </div>

    <n-card v-if="activeProvider" size="small" style="margin-bottom:16px" :bordered="true">
      <template #header>
        <n-space>
          <span style="font-size:18px">{{ providerIcon(activeProvider.type) }}</span>
          <span style="font-weight:600">{{ activeProvider.name }}</span>
          <n-tag :bordered="false" type="success" size="tiny">已激活</n-tag>
          <n-tag v-if="activeProvider.selected_model" :bordered="false" size="tiny">{{ activeProvider.selected_model }}</n-tag>
        </n-space>
      </template>
      <n-text depth="3" style="font-size:12px">{{ activeProvider.base_url }} · 已启用 {{ activeProvider.enabled_models?.length || 0 }}/{{ activeProvider.models?.length || 0 }} 个模型</n-text>
    </n-card>
    <n-alert v-else type="warning" :bordered="false" style="margin-bottom:16px">暂无激活的 LLM Provider。请添加并激活一个 Provider 以启用 AI 复盘功能。</n-alert>

    <n-spin :show="loading">
      <n-empty v-if="!loading && providers.length === 0" description="暂无 Provider" />
      <n-space vertical size="small" v-else>
        <n-card v-for="p in providers" :key="p.id" size="small" :bordered="true">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div style="display:flex;align-items:center;gap:8px">
              <span style="font-size:20px">{{ providerIcon(p.type) }}</span>
              <div>
                <div style="font-weight:600;font-size:14px">{{ p.name }}</div>
                <div style="font-size:11px;color:#8b8f97">{{ p.base_url }} · {{ p.models?.length || 0 }} 模型</div>
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:6px">
              <n-tag v-if="p.is_active" :bordered="false" type="success" size="tiny">激活</n-tag>
              <n-tag v-if="p.selected_model" :bordered="false" size="tiny">{{ p.selected_model }}</n-tag>
              <n-button size="tiny" quaternary @click="activateProvider(p.id)" :disabled="p.is_active">激活</n-button>
              <n-button size="tiny" quaternary @click="testProvider(p.id)" :loading="testing">测试</n-button>
              <n-button size="tiny" quaternary @click="openEdit(p)">编辑</n-button>
              <n-popconfirm @positive-click="deleteProvider(p.id)">
                <template #trigger><n-button size="tiny" quaternary type="error">删除</n-button></template>
                确认删除 {{ p.name }}？
              </n-popconfirm>
            </div>
          </div>
        </n-card>
      </n-space>
    </n-spin>

    <n-modal v-model:show="showForm" :title="editing ? '编辑 Provider' : '添加 Provider'"
      preset="card" style="width:560px" :mask-closable="false">
      <n-form label-placement="left" label-width="100px">
        <n-form-item label="名称">
          <n-input v-model:value="formData.name" placeholder="如: DeepSeek, OpenAI, 我的本地模型" />
        </n-form-item>
        <n-form-item label="类型">
          <n-select v-model:value="formData.type"
            :options="[
              { label: 'OpenAI 兼容', value: 'openai' },
              { label: 'Ollama（本地）', value: 'ollama' },
            ]" />
        </n-form-item>
        <n-form-item label="API Key">
          <n-input v-model:value="formData.api_key" type="password" :placeholder="editing ? '留空则不修改' : 'sk-...'" />
        </n-form-item>
        <n-form-item label="Base URL">
          <n-input v-model:value="formData.base_url" placeholder="https://api.openai.com/v1" />
        </n-form-item>

        <n-divider title-position="left">连接测试</n-divider>
        <n-form-item label=" ">
          <n-button @click="testConnection" :loading="testing" secondary>测试连接并获取模型</n-button>
          <template #feedback>点击测试连接，成功后自动获取可用模型列表</template>
        </n-form-item>

        <n-divider v-if="testResult || formData.models.length" title-position="left">可用模型</n-divider>

        <n-form-item v-if="testResult || formData.models.length" label=" ">
          <div style="width:100%">
            <n-empty v-if="formData.models.length === 0" description="暂无模型，请先测试连接" size="small" />
            <div v-for="m in formData.models" :key="m"
              style="display:flex;align-items:center;justify-content:space-between;padding:4px 0">
              <div style="display:flex;align-items:center;gap:8px">
                <n-checkbox :checked="formData.enabled_models.includes(m)" @update:checked="() => toggleModel(m)" />
                <span :style="{ fontWeight: formData.selected_model === m ? 600 : 400 }">{{ m }}</span>
                <n-tag v-if="formData.selected_model === m" :bordered="false" size="tiny" type="primary">当前</n-tag>
              </div>
              <n-button v-if="formData.enabled_models.includes(m) && formData.selected_model !== m"
                size="tiny" quaternary @click="formData.selected_model = m">设为当前</n-button>
            </div>
          </div>
          <template #feedback>勾选要启用的模型，点击"设为当前"选择激活模型</template>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showForm = false">取消</n-button>
          <n-button type="primary" @click="saveProvider">保存</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>