<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'

const { t } = useI18n()
const message = useMessage()

function errOf(res: any, d: any): string {
  return d?.error || d?.detail || res.statusText || `HTTP ${res.status}`
}

// ── MCP 连接器 ──
const mcpConnectors = ref<any[]>([])
const showMcpModal = ref(false)
const mcpEditingId = ref<string | null>(null)  // null=无编辑, 'new'=新增, 其他=编辑某卡片
const mcpSaving = ref(false)
const mcpTab = ref<'form' | 'json'>('form')
const mcpForm = ref({ name: '', type: 'stdio', command: '', args: '', url: '', envText: '' })

// 来源平台徽章文案
const PLATFORM_LABELS: Record<string, string> = {
  smithery: 'Smithery', modelscope: '魔搭', mcpso: 'mcp.so', paste: '粘贴导入',
}

function needsCompletion(c: any): boolean {
  // env 中含 YOUR_ 或空值占位符 → 待补全
  const env = c.env || {}
  return Object.values(env).some((v: any) => v === '' || v == null || String(v).includes('YOUR_'))
}

// ── env 键值对编辑（每行 KEY=VALUE）──
function parseEnvText(text: string): Record<string, string> {
  const env: Record<string, string> = {}
  for (const line of (text || '').split('\n')) {
    const s = line.trim()
    if (!s || s.startsWith('#')) continue
    const idx = s.indexOf('=')
    if (idx <= 0) continue
    env[s.slice(0, idx).trim()] = s.slice(idx + 1).trim()
  }
  return env
}

function envToText(env: Record<string, string> | undefined | null): string {
  if (!env) return ''
  return Object.entries(env).map(([k, v]) => `${k}=${v ?? ''}`).join('\n')
}

async function loadMcpConnectors() {
  try {
    const r = await fetch('/api/mcp/connectors')
    const d = await r.json()
    mcpConnectors.value = d.connectors || []
  } catch (e) { /* ignore */ }
}

function openMcpNew() {
  mcpEditingId.value = 'new'
  mcpTab.value = 'form'
  mcpForm.value = { name: '', type: 'stdio', command: '', args: '', url: '', envText: '' }
  resetJsonTab()
  showMcpModal.value = true
}

function openMcpEdit(id: string) {
  const c = mcpConnectors.value.find(x => x.id === id)
  if (!c) return
  mcpEditingId.value = id
  mcpTab.value = 'form'
  mcpForm.value = {
    name: c.name || '',
    type: c.type || 'stdio',
    command: c.command || '',
    args: Array.isArray(c.args) ? c.args.join(', ') : (c.args || ''),
    url: c.url || '',
    envText: envToText(c.env),
  }
  resetJsonTab()
  showMcpModal.value = true
}

function cancelMcpEdit() {
  showMcpModal.value = false  // mcpEditingId 在 @after-leave 中重置，避免关闭动画期间标题闪变
}

async function saveMcpConnector() {
  if (!mcpForm.value.name) { message.warning('请输入连接器名称'); return }
  mcpSaving.value = true
  try {
    const body: any = { name: mcpForm.value.name, type: mcpForm.value.type }
    if (mcpForm.value.type === 'stdio') {
      body.command = mcpForm.value.command
      body.args = mcpForm.value.args.split(',').map(s => s.trim()).filter(Boolean)
    } else {
      body.url = mcpForm.value.url
    }
    body.env = parseEnvText(mcpForm.value.envText)
    const isNew = mcpEditingId.value === 'new'
    const res = await fetch(isNew ? '/api/mcp/connectors' : `/api/mcp/connectors/${mcpEditingId.value}`, {
      method: isNew ? 'POST' : 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    let d: any = {}
    try { d = await res.json() } catch { /* 响应体非 JSON */ }
    // 同时检查 HTTP 状态码与响应体错误字段，避免失败时显示假成功消息
    if (!res.ok || d.error || d.detail) {
      const detail = d.error || d.detail || res.statusText || `HTTP ${res.status}`
      message.error(`保存失败: ${detail}`)
      return
    }
    message.success(isNew ? '连接器已新增' : '连接器已更新')
    showMcpModal.value = false  // 仅关闭 Modal；mcpEditingId 在 @after-leave 中重置，避免标题闪变
    await loadMcpConnectors()
  } catch (e: any) { message.error('保存失败') }
  finally { mcpSaving.value = false }
}

async function deleteMcpConnector(id: string) {
  try {
    await fetch(`/api/mcp/connectors/${id}`, { method: 'DELETE' })
    message.success('连接器已删除')
    await loadMcpConnectors()
  } catch { message.error('删除失败') }
}

async function toggleMcpConnector(id: string) {
  try {
    await fetch(`/api/mcp/connectors/${id}/toggle`, { method: 'POST' })
    await loadMcpConnectors()
  } catch { message.error('切换失败') }
}

// ── JSON 导入（编辑 Modal 内的标签页）──
const jsonText = ref('')
const jsonPolicy = ref('skip')
const jsonParsing = ref(false)
const jsonPreview = ref<any | null>(null)   // {ok: [...], errors: [...]}
const jsonImporting = ref(false)
const jsonResults = ref<any[]>([])          // 导入后的逐条结果

const policyOptions = [
  { label: '跳过重名', value: 'skip' },
  { label: '覆盖重名', value: 'overwrite' },
  { label: '重名自动改名', value: 'rename' },
]

function resetJsonTab() {
  jsonText.value = ''
  jsonPreview.value = null
  jsonResults.value = []
}

async function parseJsonPreview() {
  const text = jsonText.value.trim()
  if (!text) { message.warning('请粘贴 mcpServers JSON'); return }
  jsonParsing.value = true
  jsonPreview.value = null
  jsonResults.value = []
  try {
    const res = await fetch('/api/mcp/store/parse-json', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw: text }),
    })
    let d: any = {}
    try { d = await res.json() } catch { /* ignore */ }
    if (!res.ok) { message.error(`解析失败: ${errOf(res, d)}`); return }
    jsonPreview.value = d
  } catch { message.error('解析请求失败') }
  finally { jsonParsing.value = false }
}

async function doJsonImport(text: string, policy: string, platform: string): Promise<any | null> {
  try {
    const res = await fetch('/api/mcp/store/import-json', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw: text, conflict_policy: policy, platform }),
    })
    let d: any = {}
    try { d = await res.json() } catch { /* ignore */ }
    if (!res.ok || !d.ok) { message.error(`导入失败: ${errOf(res, d)}`); return null }
    return d
  } catch { message.error('导入请求失败'); return null }
}

async function importJsonTab() {
  const text = jsonText.value.trim()
  if (!text) { message.warning('请粘贴 mcpServers JSON'); return }
  jsonImporting.value = true
  jsonResults.value = []
  try {
    const d = await doJsonImport(text, jsonPolicy.value, 'paste')
    if (!d) return
    jsonResults.value = [...(d.results || []), ...((d.parse_errors || []).map((e: any) =>
      ({ name: e.name || '(整体)', action: 'error', error: e.reason })))]
    jsonPreview.value = null
    message.success(`导入完成：成功 ${d.imported} 条` +
      (d.overwritten ? `，覆盖 ${d.overwritten} 条` : '') +
      (d.skipped ? `，跳过 ${d.skipped} 条` : ''))
    await loadMcpConnectors()
  } finally { jsonImporting.value = false }
}

function actionLabel(r: any): string {
  switch (r.action) {
    case 'imported': return r.final_name ? '已导入' : '已导入'
    case 'renamed': return `已导入（改名为 ${r.final_name}）`
    case 'overwritten': return '已覆盖'
    case 'skipped': return `已跳过（${r.reason || '重名'}）`
    case 'error': return `失败：${r.error || '未知错误'}`
    default: return r.action
  }
}

function actionColor(r: any): string {
  if (['imported', 'renamed', 'overwritten'].includes(r.action)) return '#18a058'
  if (r.action === 'skipped') return '#f0a020'
  return '#d03050'
}

// ── 市场 Modal ──
const showMarketModal = ref(false)
const platforms = ref<any[]>([])
const selectedPlatform = ref('smithery')
const loadingPlatforms = ref(false)

// Smithery API Key（Agent 设置，打码显示）
const smitheryKey = ref('')
const smitheryKeySaving = ref(false)
const smitheryKeyConfigured = ref(false)
const smitheryKeyMasked = ref('')

async function loadAgentSettings() {
  try {
    const res = await fetch('/api/ai/agent-settings')
    if (!res.ok) return
    const d = await res.json()
    smitheryKeyConfigured.value = !!d.smithery_api_key_configured
    smitheryKeyMasked.value = d.smithery_api_key || ''
  } catch { /* ignore */ }
}

async function loadPlatforms() {
  const r = await fetch('/api/mcp/store/platforms')
  const d = await r.json()
  platforms.value = d.platforms || []
}

async function saveSmitheryKey() {
  const val = smitheryKey.value.trim()
  if (!val) { message.warning(t('ai.smithery_key_empty_hint')); return }
  smitheryKeySaving.value = true
  try {
    const res = await fetch('/api/ai/agent-settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ smithery_api_key: val }),
    })
    let d: any = {}
    try { d = await res.json() } catch { /* 响应体非 JSON */ }
    if (!res.ok || d.error || d.detail) {
      message.error(`${t('ai.save_failed', { error: '' })}: ${errOf(res, d)}`)
      return
    }
    smitheryKey.value = ''
    smitheryKeyConfigured.value = !!d.smithery_api_key_configured
    smitheryKeyMasked.value = d.smithery_api_key || ''
    message.success(t('ai.saved'))
    // 刷新平台列表：smithery 从直链模式切换为系统内搜索模式
    try { await loadPlatforms() } catch { /* ignore */ }
  } catch { message.error(t('ai.save_failed', { error: '' })) }
  finally { smitheryKeySaving.value = false }
}

async function clearSmitheryKey() {
  smitheryKeySaving.value = true
  try {
    const res = await fetch('/api/ai/agent-settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ smithery_api_key: '' }),
    })
    let d: any = {}
    try { d = await res.json() } catch { /* 响应体非 JSON */ }
    if (!res.ok || d.error || d.detail) {
      message.error(`${t('ai.save_failed', { error: '' })}: ${errOf(res, d)}`)
      return
    }
    smitheryKey.value = ''
    smitheryKeyConfigured.value = false
    smitheryKeyMasked.value = ''
    message.success(t('ai.smithery_key_cleared'))
    try { await loadPlatforms() } catch { /* ignore */ }
  } catch { message.error(t('ai.save_failed', { error: '' })) }
  finally { smitheryKeySaving.value = false }
}

// smithery 搜索
const searchQuery = ref('')
const searching = ref(false)
const searchResults = ref<any[]>([])
const searchError = ref('')
const searchDone = ref(false)
const installingQn = ref('')

// 粘贴导入区（smithery 无 Key / mcp.so 共用）
const mkPasteText = ref('')
const mkPastePolicy = ref('skip')
const mkPasteImporting = ref(false)
const mkPasteResults = ref<any[]>([])

// 魔搭模板
const msTemplates = ref<any[]>([])
const tplValues = ref<Record<string, Record<string, string>>>({})
const installingTpl = ref('')

const currentPlatform = computed(() =>
  platforms.value.find((p: any) => p.id === selectedPlatform.value))

async function openMarketModal() {
  showMarketModal.value = true
  searchError.value = ''
  mkPasteResults.value = []
  if (!platforms.value.length) {
    loadingPlatforms.value = true
    try {
      await loadPlatforms()
    } catch { message.error('平台列表加载失败') }
    finally { loadingPlatforms.value = false }
  }
  await loadAgentSettings()
  if (!msTemplates.value.length) {
    try {
      const r = await fetch('/api/mcp/store/templates')
      const d = await r.json()
      msTemplates.value = d.templates || []
      for (const tpl of msTemplates.value) {
        tplValues.value[tpl.id] = {}
        for (const f of (tpl.fields || [])) tplValues.value[tpl.id][f.key] = ''
      }
    } catch { /* ignore */ }
  }
}

function openPlatform(url: string) {
  window.open(url, '_blank')
}

async function doSmitherySearch() {
  const q = searchQuery.value.trim()
  if (!q) { message.warning('请输入搜索关键词'); return }
  searching.value = true
  searchError.value = ''
  searchResults.value = []
  searchDone.value = false
  try {
    const res = await fetch(`/api/mcp/store/search?platform=smithery&q=${encodeURIComponent(q)}`)
    let d: any = {}
    try { d = await res.json() } catch { /* ignore */ }
    if (!res.ok) { searchError.value = errOf(res, d); return }
    searchResults.value = d.results || []
    searchDone.value = true
  } catch { searchError.value = '网络错误，搜索失败' }
  finally { searching.value = false }
}

async function installSmithery(item: any) {
  installingQn.value = item.qualifiedName || item.name
  try {
    const res = await fetch(`/api/mcp/store/detail?platform=smithery&qualified_name=${encodeURIComponent(item.qualifiedName || item.name)}`)
    let d: any = {}
    try { d = await res.json() } catch { /* ignore */ }
    if (!res.ok || !d.connectors?.length) { message.error(`获取详情失败: ${errOf(res, d)}`); return }
    // 把后端转换好的连接器重新打包为 mcpServers JSON，走统一导入链路
    const servers: Record<string, any> = {}
    for (const c of d.connectors) {
      servers[c.name] = {
        type: c.type, command: c.command || undefined, args: c.args?.length ? c.args : undefined,
        url: c.url || undefined, env: Object.keys(c.env || {}).length ? c.env : undefined,
        headers: Object.keys(c.headers || {}).length ? c.headers : undefined,
        description: c.description || undefined,
      }
    }
    const imp = await doJsonImport(JSON.stringify({ mcpServers: servers }, null, 2), 'rename', 'smithery')
    if (!imp) return
    message.success(`「${item.name}」已安装 ${imp.imported} 个连接器` +
      (imp.skipped ? `，跳过 ${imp.skipped} 条` : ''))
    await loadMcpConnectors()
  } catch { message.error('安装失败') }
  finally { installingQn.value = '' }
}

async function mkPasteImport(platform: string) {
  const text = mkPasteText.value.trim()
  if (!text) { message.warning('请粘贴 mcpServers JSON'); return }
  mkPasteImporting.value = true
  mkPasteResults.value = []
  try {
    const d = await doJsonImport(text, mkPastePolicy.value, platform)
    if (!d) return
    mkPasteResults.value = [...(d.results || []), ...((d.parse_errors || []).map((e: any) =>
      ({ name: e.name || '(整体)', action: 'error', error: e.reason })))]
    message.success(`导入完成：成功 ${d.imported} 条` +
      (d.overwritten ? `，覆盖 ${d.overwritten} 条` : '') +
      (d.skipped ? `，跳过 ${d.skipped} 条` : ''))
    mkPasteText.value = ''
    await loadMcpConnectors()
  } finally { mkPasteImporting.value = false }
}

async function installTemplate(tpl: any) {
  const vals = tplValues.value[tpl.id] || {}
  const name = (vals['name'] || '').trim()
  if (!name) { message.warning('请填写连接器名称'); return }
  installingTpl.value = tpl.id
  try {
    const cfg: any = {}
    const env: Record<string, string> = {}
    for (const f of (tpl.fields || [])) {
      const v = (vals[f.key] || '').trim()
      if (f.key === 'name') continue
      if (f.key === 'url') cfg.url = v
      else if (f.key.startsWith('env.')) env[f.key.slice(4)] = v
    }
    if (tpl.type === 'stdio') { cfg.command = tpl.command; cfg.args = tpl.args || [] }
    if (Object.keys(env).length) cfg.env = env
    // 必填校验
    if (tpl.type === 'sse' && !cfg.url) { message.warning('请填写 SSE URL'); return }
    for (const f of (tpl.fields || [])) {
      if (f.key.startsWith('env.') && !(vals[f.key] || '').trim()) {
        message.warning(`请填写 ${f.label}`); return
      }
    }
    const d = await doJsonImport(JSON.stringify({ mcpServers: { [name]: cfg } }, null, 2), 'rename', 'modelscope')
    if (!d) return
    message.success(`「${name}」已安装`)
    tplValues.value[tpl.id] = Object.fromEntries((tpl.fields || []).map((f: any) => [f.key, '']))
    await loadMcpConnectors()
  } finally { installingTpl.value = '' }
}

onMounted(loadMcpConnectors)
</script>

<template>
  <n-card size="small" :bordered="true">
    <template #header>
      <span>MCP 连接器 ({{ mcpConnectors.length }})</span>
    </template>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px;padding:4px">
      <div v-for="c in mcpConnectors" :key="c.id">
        <div @click="openMcpEdit(c.id)"
          style="border:2px solid var(--n-border-color);border-radius:10px;padding:16px;cursor:pointer;transition:border-color 0.2s;background:transparent;min-height:120px;display:flex;flex-direction:column"
          :style="{ borderColor: c.enabled ? '#f0b90b' : 'var(--n-border-color)' }">
          <!-- 顶部：名称 + 启用开关 -->
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span style="font-weight:600;font-size:15px">{{ c.name }}</span>
            <div @click.stop>
              <n-switch :value="!!c.enabled" size="small" @update:value="() => toggleMcpConnector(c.id)" :round="true" />
            </div>
          </div>
          <!-- 类型 + 来源 + 待补全 标签 -->
          <div style="margin-bottom:6px;display:flex;gap:6px;flex-wrap:wrap">
            <n-tag :bordered="false" size="tiny" :type="c.type === 'stdio' ? 'info' : 'success'">{{ c.type }}</n-tag>
            <n-tag v-if="c.source && c.source.platform" :bordered="false" size="tiny" type="success">
              {{ PLATFORM_LABELS[c.source.platform] || c.source.platform }}
            </n-tag>
            <n-tag v-if="needsCompletion(c)" :bordered="false" size="tiny" type="warning">待补全</n-tag>
          </div>
          <!-- URL 或 Command -->
          <div style="font-size:11px;color:#8b8f97;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:8px">
            {{ c.type === 'sse' ? (c.url || '') : [c.command, ...(Array.isArray(c.args) ? c.args : [])].filter(Boolean).join(' ') }}
          </div>
          <!-- 底部：删除按钮 -->
          <div style="margin-top:auto;display:flex;justify-content:flex-end;align-items:center">
            <div @click.stop>
              <n-popconfirm @positive-click="deleteMcpConnector(c.id)">
                <template #trigger><n-button size="tiny" quaternary type="error">✕</n-button></template>
                {{ t('ai.confirm_delete_connector') }}
              </n-popconfirm>
            </div>
          </div>
        </div>
      </div>

      <!-- 新增连接器空白卡片 -->
      <div v-if="!showMcpModal" @click="openMcpNew"
        style="border:2px dashed var(--n-border-color);border-radius:10px;padding:16px;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:pointer;min-height:120px;transition:border-color 0.2s;background:transparent"
        @mouseover="(e:any) => e.currentTarget.style.borderColor='#f0b90b'"
        @mouseout="(e:any) => e.currentTarget.style.borderColor='var(--n-border-color)'">
        <span style="font-size:26px;color:#8b8f97;margin-bottom:4px">+</span>
        <span style="font-size:13px;color:#8b8f97">新增连接器</span>
      </div>

      <!-- 从市场添加卡片 -->
      <div v-if="!showMcpModal" @click="openMarketModal"
        style="border:2px dashed var(--n-border-color);border-radius:10px;padding:16px;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:pointer;min-height:120px;transition:border-color 0.2s;background:transparent"
        @mouseover="(e:any) => e.currentTarget.style.borderColor='#18a058'"
        @mouseout="(e:any) => e.currentTarget.style.borderColor='var(--n-border-color)'">
        <span style="font-size:22px;color:#8b8f97;margin-bottom:4px">🛒</span>
        <span style="font-size:13px;color:#8b8f97">从市场添加</span>
      </div>
    </div>

    <!-- MCP 连接器编辑 Modal（表单 / JSON 导入 双标签页） -->
    <n-modal v-model:show="showMcpModal" :mask-closable="false" preset="card" style="max-width:680px" @after-leave="mcpEditingId = null" :title="mcpEditingId === 'new' ? '新增 MCP 连接器' : '编辑 MCP 连接器'">
      <n-tabs v-model:value="mcpTab" type="line" animated size="small">
        <!-- ══ 表单标签页 ══ -->
        <n-tab-pane name="form" tab="表单">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px">
            <div>
              <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">名称</div>
              <n-input v-model:value="mcpForm.name" size="small" placeholder="如：filesystem" />
            </div>
            <div>
              <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">类型</div>
              <n-select v-model:value="mcpForm.type" size="small" :options="[
                { label: 'stdio（本地进程）', value: 'stdio' },
                { label: 'sse（远程服务）', value: 'sse' },
              ]" />
            </div>
            <div v-if="mcpForm.type === 'stdio'" style="grid-column:span 2">
              <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">Command</div>
              <n-input v-model:value="mcpForm.command" size="small" placeholder="如：npx 或 python" />
            </div>
            <div v-if="mcpForm.type === 'stdio'" style="grid-column:span 2">
              <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">Args（逗号分隔）</div>
              <n-input v-model:value="mcpForm.args" size="small" placeholder="如：-y, @modelcontextprotocol/server-filesystem, /path" />
            </div>
            <div v-if="mcpForm.type === 'sse'" style="grid-column:span 2">
              <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">URL</div>
              <n-input v-model:value="mcpForm.url" size="small" placeholder="http://localhost:8080/sse" />
            </div>
            <div style="grid-column:span 2">
              <div style="font-size:12px;color:#8b8f97;margin-bottom:4px">环境变量（可选，每行 KEY=VALUE）</div>
              <n-input v-model:value="mcpForm.envText" size="small" type="textarea" :rows="3"
                placeholder="API_KEY=xxx&#10;TOKEN=yyy" />
            </div>
          </div>
        </n-tab-pane>

        <!-- ══ JSON 导入标签页 ══ -->
        <n-tab-pane name="json" tab="JSON 导入">
          <n-alert type="info" :bordered="false" style="margin:8px 0">
            粘贴业界统一的 mcpServers JSON（支持批量），如：
            <code>{"mcpServers": {"fs": {"command": "npx", "args": [...]}}}</code>
          </n-alert>
          <n-input v-model:value="jsonText" type="textarea" :rows="7"
            placeholder='{&#10;  "mcpServers": {&#10;    "filesystem": {&#10;      "command": "npx",&#10;      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]&#10;    }&#10;  }&#10;}' />
          <div style="display:flex;align-items:center;justify-content:space-between;margin-top:10px;flex-wrap:wrap;gap:8px">
            <n-radio-group v-model:value="jsonPolicy" size="small">
              <n-radio-button v-for="opt in policyOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </n-radio-button>
            </n-radio-group>
            <n-space size="small">
              <n-button size="small" :loading="jsonParsing" @click="parseJsonPreview">解析预览</n-button>
              <n-button size="small" type="primary" :loading="jsonImporting" @click="importJsonTab">导入</n-button>
            </n-space>
          </div>

          <!-- 解析预览 -->
          <div v-if="jsonPreview" style="margin-top:12px">
            <n-text depth="3" style="font-size:12px">
              将导入 {{ jsonPreview.ok?.length || 0 }} 个连接器{{ jsonPreview.errors?.length ? `，${jsonPreview.errors.length} 条解析失败` : '' }}：
            </n-text>
            <div v-for="c in jsonPreview.ok" :key="'pv-' + c.name" class="preview-row" style="border-left:3px solid #18a058">
              <n-tag size="tiny" :bordered="false" :type="c.type === 'stdio' ? 'info' : 'success'">{{ c.type }}</n-tag>
              <b style="margin-left:6px">{{ c.name }}</b>
              <span style="opacity:0.65;margin-left:8px;font-size:12px">
                {{ c.type === 'sse' ? c.url : [c.command, ...(c.args || [])].filter(Boolean).join(' ') }}
              </span>
            </div>
            <div v-for="(e, i) in jsonPreview.errors" :key="'pe-' + i" class="preview-row" style="border-left:3px solid #d03050;color:#d03050">
              <b style="margin-right:6px">{{ e.name || '(整体)' }}</b>{{ e.reason }}
            </div>
          </div>

          <!-- 导入逐条结果 -->
          <div v-if="jsonResults.length" style="margin-top:12px">
            <n-text depth="3" style="font-size:12px">导入结果：</n-text>
            <div v-for="(r, i) in jsonResults" :key="'jr-' + i" class="preview-row"
              :style="{ borderLeft: `3px solid ${actionColor(r)}`, color: actionColor(r) }">
              <b style="margin-right:6px">{{ r.name }}</b>{{ actionLabel(r) }}
            </div>
          </div>
        </n-tab-pane>
      </n-tabs>

      <template #footer>
        <div v-if="mcpTab === 'form'" style="display:flex;justify-content:flex-end;gap:8px">
          <n-button size="small" quaternary @click="cancelMcpEdit">{{ t('ai.cancel') }}</n-button>
          <n-button type="primary" size="small" @click="saveMcpConnector" :loading="mcpSaving">{{ t('ai.save') }}</n-button>
        </div>
        <div v-else style="display:flex;justify-content:flex-end">
          <n-button size="small" quaternary @click="cancelMcpEdit">关闭</n-button>
        </div>
      </template>
    </n-modal>

    <!-- ══ MCP 市场 Modal ══ -->
    <n-modal v-model:show="showMarketModal" preset="card" title="从 MCP 市场添加"
      style="width: 760px; max-width: 94vw">
      <n-spin :show="loadingPlatforms">
        <n-grid :cols="3" :x-gap="10" :y-gap="10" responsive="screen" item-responsive>
          <n-gi v-for="p in platforms" :key="p.id" span="3 m:1">
            <div class="platform-card" :class="{ active: selectedPlatform === p.id }"
              @click="selectedPlatform = p.id">
              <div class="platform-top">
                <span class="platform-name">{{ p.name }}</span>
                <n-tag size="tiny" :type="p.level === 'api' ? 'success' : (p.level === 'template' ? 'info' : 'default')" :bordered="false">
                  {{ p.grade }} 级 · {{ p.level === 'api' ? '系统内搜索' : (p.level === 'template' ? '模板接入' : '跳转浏览') }}
                </n-tag>
              </div>
              <div class="platform-desc">{{ p.description }}</div>
              <n-button size="tiny" quaternary @click.stop="openPlatform(p.url)">打开平台 ↗</n-button>
            </div>
          </n-gi>
        </n-grid>
      </n-spin>

      <n-divider style="margin: 14px 0" />

      <!-- ── Smithery：有 Key 系统内搜索 / 无 Key 粘贴引导 ── -->
      <div v-if="selectedPlatform === 'smithery'">
        <!-- Smithery API Key 配置区 -->
        <div style="border:1px solid rgba(128,128,128,0.25);border-radius:8px;padding:12px;margin-bottom:12px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:6px">
            <span style="font-weight:600;font-size:13px">{{ t('ai.smithery_key_title') }}</span>
            <n-tag v-if="smitheryKeyConfigured" size="tiny" :bordered="false" type="success">
              {{ t('ai.smithery_key_configured') }}{{ smitheryKeyMasked ? `（${smitheryKeyMasked}）` : '' }}
            </n-tag>
            <n-tag v-else size="tiny" :bordered="false" type="warning">{{ t('ai.smithery_key_not_configured') }}</n-tag>
          </div>
          <n-input-group>
            <n-input v-model:value="smitheryKey" type="password" show-password-on="click"
              :placeholder="smitheryKeyConfigured ? t('ai.keep_empty') : t('ai.smithery_key_placeholder')"
              style="flex:1" @keydown.enter="saveSmitheryKey" />
            <n-button type="primary" :loading="smitheryKeySaving" @click="saveSmitheryKey">{{ t('ai.save') }}</n-button>
            <n-button :disabled="!smitheryKeyConfigured || smitheryKeySaving" @click="clearSmitheryKey">{{ t('ai.smithery_key_clear') }}</n-button>
          </n-input-group>
        </div>

        <template v-if="currentPlatform?.level === 'api'">
          <n-input-group>
            <n-input v-model:value="searchQuery" placeholder="搜索 MCP 服务器，如 filesystem / github …"
              clearable @keydown.enter="doSmitherySearch" />
            <n-button type="primary" :loading="searching" @click="doSmitherySearch">搜索</n-button>
          </n-input-group>
          <div style="margin-top:12px">
            <n-spin :show="searching">
              <n-alert v-if="searchError" type="warning" :bordered="false" style="margin-bottom:8px">
                {{ searchError }}
              </n-alert>
              <n-empty v-else-if="searchDone && searchResults.length === 0" size="small" description="未找到相关服务器" />
              <n-space vertical v-if="searchResults.length > 0" size="small">
                <n-card v-for="item in searchResults" :key="item.qualifiedName || item.name" size="small">
                  <template #header>
                    <span style="font-weight:600">{{ item.name }}</span>
                    <n-text depth="3" style="font-size:11px;margin-left:8px">{{ item.qualifiedName }}</n-text>
                  </template>
                  <template #header-extra>
                    <n-button size="tiny" type="primary" secondary
                      :loading="installingQn === (item.qualifiedName || item.name)"
                      @click="installSmithery(item)">安装</n-button>
                  </template>
                  <span class="result-desc">{{ item.description }}</span>
                </n-card>
              </n-space>
            </n-spin>
          </div>
        </template>
        <template v-else>
          <n-alert type="warning" :bordered="false" style="margin-bottom:8px">
            未配置 Smithery API Key（环境变量 SMITHERY_API_KEY），暂不支持系统内搜索安装。
            请打开平台网页浏览服务器，在详情页复制 mcpServers JSON 后在下方粘贴导入；
            配置 Key 后即可系统内搜索 + 一键安装。
          </n-alert>
          <n-input v-model:value="mkPasteText" type="textarea" :rows="6"
            placeholder='粘贴 mcpServers JSON，如 {"mcpServers": {"github": {"command": "npx", ...}}}' />
          <div style="display:flex;align-items:center;justify-content:space-between;margin-top:10px;flex-wrap:wrap;gap:8px">
            <n-radio-group v-model:value="mkPastePolicy" size="small">
              <n-radio-button v-for="opt in policyOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</n-radio-button>
            </n-radio-group>
            <n-button type="primary" size="small" :loading="mkPasteImporting" @click="mkPasteImport('smithery')">导入</n-button>
          </div>
        </template>
      </div>

      <!-- ── 魔搭：预置模板 ── -->
      <div v-else-if="selectedPlatform === 'modelscope'">
        <n-space vertical size="medium">
          <n-card v-for="tpl in msTemplates" :key="tpl.id" size="small" :title="tpl.title">
            <template #header-extra>
              <n-tag size="tiny" :bordered="false" :type="tpl.type === 'sse' ? 'success' : 'info'">{{ tpl.type }}</n-tag>
            </template>
            <div style="font-size:12px;opacity:0.75;margin-bottom:10px">{{ tpl.description }}</div>
            <n-space vertical size="small">
              <div v-for="f in tpl.fields" :key="f.key">
                <div style="font-size:12px;color:#8b8f97;margin-bottom:3px">{{ f.label }}</div>
                <n-input v-model:value="tplValues[tpl.id][f.key]" size="small"
                  :type="f.secret ? 'password' : 'text'" :placeholder="f.placeholder" />
              </div>
            </n-space>
            <n-text depth="3" style="font-size:11px;display:block;margin-top:8px">{{ tpl.note }}</n-text>
            <div style="margin-top:10px;display:flex;justify-content:space-between;align-items:center">
              <n-button size="tiny" quaternary @click="openPlatform(tpl.platform_url)">打开魔搭 MCP 广场 ↗</n-button>
              <n-button size="small" type="primary" :loading="installingTpl === tpl.id"
                @click="installTemplate(tpl)">安装</n-button>
            </div>
          </n-card>
        </n-space>
      </div>

      <!-- ── mcp.so：直连跳转 + 粘贴导入 ── -->
      <div v-else-if="selectedPlatform === 'mcpso'">
        <n-alert type="info" :bordered="false" style="margin-bottom:8px">
          请先在浏览器打开 mcp.so，进入服务器详情页复制 mcpServers JSON 配置，回到本系统粘贴导入。
        </n-alert>
        <n-input v-model:value="mkPasteText" type="textarea" :rows="6"
          placeholder='粘贴 mcpServers JSON，如 {"mcpServers": {"weather": {"url": "https://..."}}}' />
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:10px;flex-wrap:wrap;gap:8px">
          <n-radio-group v-model:value="mkPastePolicy" size="small">
            <n-radio-button v-for="opt in policyOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</n-radio-button>
          </n-radio-group>
          <n-button type="primary" size="small" :loading="mkPasteImporting" @click="mkPasteImport('mcpso')">导入</n-button>
        </div>
      </div>

      <!-- 市场导入逐条结果 -->
      <div v-if="mkPasteResults.length" style="margin-top:12px">
        <n-text depth="3" style="font-size:12px">导入结果：</n-text>
        <div v-for="(r, i) in mkPasteResults" :key="'mr-' + i" class="preview-row"
          :style="{ borderLeft: `3px solid ${actionColor(r)}`, color: actionColor(r) }">
          <b style="margin-right:6px">{{ r.name }}</b>{{ actionLabel(r) }}
        </div>
      </div>
    </n-modal>
  </n-card>
</template>

<style scoped>
.platform-card {
  border: 1px solid rgba(128, 128, 128, 0.25);
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  display: flex;
  flex-direction: column;
  gap: 6px;
  height: 100%;
}
.platform-card:hover {
  border-color: rgba(240, 185, 11, 0.6);
}
.platform-card.active {
  border-color: #f0b90b;
  background: rgba(240, 185, 11, 0.06);
}
.platform-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.platform-name {
  font-weight: 700;
  font-size: 14px;
}
.platform-desc {
  font-size: 12px;
  opacity: 0.7;
  line-height: 1.5;
  flex: 1;
}
.result-desc {
  font-size: 12px;
  opacity: 0.75;
  word-break: break-all;
}
.preview-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
  padding: 6px 10px;
  margin-top: 6px;
  border-radius: 4px;
  background: rgba(128, 128, 128, 0.06);
  font-size: 13px;
  word-break: break-all;
}
</style>
