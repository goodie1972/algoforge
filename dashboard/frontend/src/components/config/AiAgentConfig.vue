<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()

const providers = ref<any[]>([])
const activeProvider = ref<any>(null)
const loading = ref(false)
const editing = ref(false)
const showForm = ref(false)
const formData = ref({
  name: '',
  type: 'openai',
  api_key: '',
  base_url: 'https://api.openai.com/v1',
  models: [] as string[],
  selected_model: '',
  is_active: false,
})
const editId = ref('')
const testing = ref(false)

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
  formData.value = {
    name: '',
    type: 'openai',
    api_key: '',
    base_url: 'https://api.openai.com/v1',
    models: [],
    selected_model: '',
    is_active: false,
  }
  showForm.value = true
}

function openEdit(p: any) {
  editing.value = true
  editId.value = p.id
  formData.value = {
    name: p.name,
    type: p.type,
    api_key: p.api_key || '',
    base_url: p.base_url,
    models: p.models || [],
    selected_model: p.selected_model || '',
    is_active: false,
  }
  showForm.value = true
}

async function saveProvider() {
  if (!formData.value.name) {
    message.warning('请输入 Provider 名称')
    return
  }
  try {
    if (editing.value) {
      const res = await fetch(`/api/llm/providers/${editId.value}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData.value),
      })
      const d = await res.json()
      if (d.success) message.success('已更新')
    } else {
      const res = await fetch('/api/llm/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData.value),
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
    if (d.success) {
      message.success('已删除')
      await loadProviders()
    }
  } catch (e: any) {
    message.error('删除失败')
  }
}

async function activateProvider(id: string) {
  try {
    const res = await fetch(`/api/llm/providers/${id}/activate`, { method: 'POST' })
    const d = await res.json()
    if (d.success) {
      message.success('已设为激活')
      await loadProviders()
    }
  } catch (e: any) {
    message.error('激活失败')
  }
}

async function testProvider(id: string) {
  testing.value = true
  try {
    const res = await fetch(`/api/llm/providers/${id}/test`, { method: 'POST' })
    const d = await res.json()
    if (d.success) {
      const dt = d.data
      if (dt.models?.length) {
        message.success(`连接成功！发现 ${dt.models.length} 个模型: ${dt.models.slice(0,3).join(', ')}...`)
      } else if (dt.warning) {
        message.warning('连接成功，但获取模型列表失败: ' + dt.warning)
      } else {
        message.success('连接成功')
      }
      await loadProviders()
    }
  } catch (e: any) {
    message.error('测试失败: ' + (e.message || ''))
  } finally {
    testing.value = false
  }
}

function providerIcon(type: string): string {
  const icons: Record<string, string> = {
    openai: '🤖',
    ollama: '🦙',
  }
  return icons[type] || '🔌'
}

onMounted(loadProviders)
</script>

<template>
  <div>
    <!-- 头部 -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <n-text depth="2">配置 LLM Provider 用于 AI 复盘分析</n-text>
      <n-button type="primary" size="small" @click="openAdd">
        + 添加 Provider
      </n-button>
    </div>

    <!-- 当前激活状态 -->
    <n-card v-if="activeProvider" size="small" style="margin-bottom:16px" :bordered="true">
      <template #header>
        <n-space>
          <span style="font-size:18px">{{ providerIcon(activeProvider.type) }}</span>
          <span style="font-weight:600">{{ activeProvider.name }}</span>
          <n-tag :bordered="false" type="success" size="tiny">已激活</n-tag>
          <n-tag v-if="activeProvider.selected_model" :bordered="false" size="tiny">
            {{ activeProvider.selected_model }}
          </n-tag>
        </n-space>
      </template>
      <n-text depth="3" style="font-size:12px">{{ activeProvider.base_url }}</n-text>
    </n-card>

    <n-alert v-else type="warning" :bordered="false" style="margin-bottom:16px">
      暂无激活的 LLM Provider。请添加并激活一个 Provider 以启用 AI 复盘功能。
    </n-alert>

    <!-- Provider 列表 -->
    <n-spin :show="loading">
      <n-empty v-if="!loading && providers.length === 0" description="暂无 Provider" />

      <n-space vertical size="small" v-else>
        <n-card v-for="p in providers" :key="p.id" size="small" :bordered="true">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div style="display:flex;align-items:center;gap:8px">
              <span style="font-size:20px">{{ providerIcon(p.type) }}</span>
              <div>
                <div style="font-weight:600;font-size:14px">{{ p.name }}</div>
                <div style="font-size:11px;color:#8b8f97">{{ p.base_url }}</div>
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:6px">
              <n-tag v-if="p.is_active" :bordered="false" type="success" size="tiny">激活</n-tag>
              <n-tag v-if="p.selected_model" :bordered="false" size="tiny">{{ p.selected_model }}</n-tag>
              <n-button size="tiny" quaternary @click="activateProvider(p.id)" :disabled="p.is_active">
                激活
              </n-button>
              <n-button size="tiny" quaternary @click="testProvider(p.id)" :loading="testing">
                测试
              </n-button>
              <n-button size="tiny" quaternary @click="openEdit(p)">
                编辑
              </n-button>
              <n-popconfirm @positive-click="deleteProvider(p.id)">
                <template #trigger>
                  <n-button size="tiny" quaternary type="error">删除</n-button>
                </template>
                确认删除 {{ p.name }}？
              </n-popconfirm>
            </div>
          </div>
        </n-card>
      </n-space>
    </n-spin>

    <!-- 添加/编辑表单 Modal -->
    <n-modal v-model:show="showForm" :title="editing ? '编辑 Provider' : '添加 Provider'"
      preset="card" style="width:520px" :mask-closable="false">
      <n-form label-placement="left" label-width="100px">
        <n-form-item label="名称">
          <n-input v-model:value="formData.name" placeholder="如: DeepSeek, OpenAI" />
        </n-form-item>
        <n-form-item label="类型">
          <n-select v-model:value="formData.type"
            :options="[
              { label: 'OpenAI 兼容', value: 'openai' },
              { label: 'Ollama（本地）', value: 'ollama' },
            ]" />
        </n-form-item>
        <n-form-item label="API Key">
          <n-input v-model:value="formData.api_key" type="password"
            :placeholder="editing ? '留空则不修改' : 'sk-...'" />
        </n-form-item>
        <n-form-item label="Base URL">
          <n-input v-model:value="formData.base_url"
            placeholder="https://api.openai.com/v1" />
        </n-form-item>
        <n-form-item label="模型">
          <n-select v-model:value="formData.selected_model"
            :options="formData.models.map(m => ({ label: m, value: m }))"
            :placeholder="editing ? '当前: ' + (formData.selected_model || '未设置') : '测试后自动填充'"
            tag filterable
            @create="(v: string) => formData.models.push(v)" />
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