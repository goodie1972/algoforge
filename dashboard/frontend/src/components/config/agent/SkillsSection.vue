<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'

const message = useMessage()

// ── 技能（支持启用/禁用管理 + 来源徽章 + 卸载）──
const skills = ref<any[]>([])
const switchingSkill = ref<string | null>(null)  // 正在切换中的技能名
const uninstalling = ref<string | null>(null)    // 正在卸载中的技能名
const rescanning = ref(false)
// 禁用技能的元信息缓存 {name: description}：兜底展示（后端现已返回全部技能）
const LS_DISABLED_SKILLS = 'disabled_skill_meta'
const disabledSkillMeta = ref<Record<string, string>>({})

function errOf(res: any, d: any): string {
  return d?.error || d?.detail || res.statusText || `HTTP ${res.status}`
}

async function loadSkills() {
  try {
    try { disabledSkillMeta.value = JSON.parse(localStorage.getItem(LS_DISABLED_SKILLS) || '{}') }
    catch { disabledSkillMeta.value = {} }
    const r = await fetch('/api/ai/skills')
    const d = await r.json()
    // 后端返回全部技能（含禁用），带 enabled / source / source_label
    const list = (d.skills || []).map((s: any) => ({
      source: 'builtin', source_label: '内置', ...s,
    }))
    // 兜底：缓存中有、但后端未返回的禁用技能
    const names = new Set(list.map((s: any) => s.name))
    const extra = Object.entries(disabledSkillMeta.value)
      .filter(([name]) => !names.has(name))
      .map(([name, description]) => ({ name, description, enabled: false, source: 'unknown', source_label: '未知' }))
    skills.value = [...list, ...extra]
  } catch (e) { /* ignore */ }
}

async function toggleSkill(skill: any, enabled: boolean) {
  switchingSkill.value = skill.name
  try {
    const res = await fetch(`/api/ai/skills/${encodeURIComponent(skill.name)}/${enabled ? 'enable' : 'disable'}`, { method: 'PUT' })
    let d: any = {}
    try { d = await res.json() } catch { /* 响应体非 JSON */ }
    if (!res.ok || !d.ok) {
      message.error(`技能切换失败: ${errOf(res, d)}`)
      await loadSkills()  // 回滚开关到真实状态
      return
    }
    skill.enabled = enabled
    if (enabled) delete disabledSkillMeta.value[skill.name]
    else disabledSkillMeta.value[skill.name] = skill.description || ''
    localStorage.setItem(LS_DISABLED_SKILLS, JSON.stringify(disabledSkillMeta.value))
    message.success(enabled ? `技能「${skill.name}」已启用` : `技能「${skill.name}」已禁用`)
  } catch { message.error('技能切换失败') }
  finally { switchingSkill.value = null }
}

async function uninstallSkill(name: string) {
  uninstalling.value = name
  try {
    const res = await fetch(`/api/ai/skill-store/${encodeURIComponent(name)}`, { method: 'DELETE' })
    let d: any = {}
    try { d = await res.json() } catch { /* ignore */ }
    if (!res.ok || d.ok === false) {
      message.error(`卸载失败: ${errOf(res, d)}`)
      return
    }
    delete disabledSkillMeta.value[name]
    localStorage.setItem(LS_DISABLED_SKILLS, JSON.stringify(disabledSkillMeta.value))
    message.success(`技能「${name}」已卸载`)
    await loadSkills()
  } catch { message.error('卸载失败') }
  finally { uninstalling.value = null }
}

async function rescanSkills() {
  rescanning.value = true
  try {
    const res = await fetch('/api/ai/skills/rescan', { method: 'POST' })
    const d = await res.json()
    if (res.ok) message.success(`重新扫描完成，共 ${d.skill_count ?? 0} 个技能`)
    else message.error(`重扫失败: ${errOf(res, d)}`)
    await loadSkills()
  } catch { message.error('重扫失败') }
  finally { rescanning.value = false }
}

// ── 来源徽章 ──
function sourceTagType(s: any): 'warning' | 'info' | 'success' | 'default' {
  if (s.source === 'builtin') return 'warning'   // 内置 = 金色
  if (s.source === 'local') return 'info'        // 本地目录 = 蓝色
  if (['skillsh', 'skillsmp', 'skillhubcn', 'paste'].includes(s.source)) return 'success'  // 平台 = 绿色
  return 'default'
}

// ── 商店 Modal ──
const showStoreModal = ref(false)
const platforms = ref<any[]>([])
const selectedPlatform = ref('skillsh')
const loadingPlatforms = ref(false)

// skill.sh 搜索
const searchQuery = ref('')
const searching = ref(false)
const searchResults = ref<any[]>([])
const searchError = ref('')
const searchDone = ref(false)
const installingRef = ref('')   // 正在安装的结果项

// 粘贴区（skillsmp / skillhub / 通用）
const pasteText = ref('')
const installingPaste = ref(false)

const currentPlatform = computed(() =>
  platforms.value.find((p: any) => p.id === selectedPlatform.value))

async function openStoreModal() {
  showStoreModal.value = true
  searchError.value = ''
  if (!platforms.value.length) {
    loadingPlatforms.value = true
    try {
      const r = await fetch('/api/ai/skill-store/platforms')
      const d = await r.json()
      platforms.value = d.platforms || []
    } catch { message.error('平台列表加载失败') }
    finally { loadingPlatforms.value = false }
  }
}

function openPlatform(url: string) {
  window.open(url, '_blank')
}

async function doSearch() {
  const q = searchQuery.value.trim()
  if (!q) { message.warning('请输入搜索关键词'); return }
  searching.value = true
  searchError.value = ''
  searchResults.value = []
  searchDone.value = false
  try {
    const res = await fetch(`/api/ai/skill-store/search?platform=skillsh&q=${encodeURIComponent(q)}`)
    let d: any = {}
    try { d = await res.json() } catch { /* ignore */ }
    if (!res.ok) { searchError.value = errOf(res, d); return }
    searchResults.value = d.results || []
    searchDone.value = true
  } catch { searchError.value = '网络错误，搜索失败' }
  finally { searching.value = false }
}

async function installFromSearch(item: any) {
  installingRef.value = item.ref || item.name
  try {
    const res = await fetch('/api/ai/skill-store/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform: 'skillsh', ref: item.ref || item.name }),
    })
    let d: any = {}
    try { d = await res.json() } catch { /* ignore */ }
    if (!res.ok || d.ok === false) { message.error(`安装失败: ${errOf(res, d)}`); return }
    message.success(`「${d.name}」已安装（默认禁用，请确认后启用）`)
    await loadSkills()
  } catch { message.error('安装失败') }
  finally { installingRef.value = '' }
}

async function installFromPaste() {
  const text = pasteText.value.trim()
  if (!text) { message.warning('请粘贴技能页链接或 SKILL.md 全文'); return }
  installingPaste.value = true
  try {
    // 自动识别：以 --- 开头（含 frontmatter）视为内容，否则视为链接
    const isContent = text.startsWith('---')
    const body = isContent
      ? { platform: selectedPlatform.value, content: text }
      : { platform: selectedPlatform.value, ref: text }
    const res = await fetch('/api/ai/skill-store/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    let d: any = {}
    try { d = await res.json() } catch { /* ignore */ }
    if (!res.ok || d.ok === false) { message.error(`安装失败: ${errOf(res, d)}`); return }
    message.success(`「${d.name}」已安装（默认禁用，请确认后启用）`)
    pasteText.value = ''
    await loadSkills()
  } catch { message.error('安装失败') }
  finally { installingPaste.value = false }
}

// ── 本地添加 Modal ──
const showLocalModal = ref(false)
const localPath = ref('')
const registeringDir = ref(false)
const localDirs = ref<string[]>([])
const removingDir = ref('')
const localContent = ref('')
const importingLocal = ref(false)

async function openLocalModal() {
  showLocalModal.value = true
  await loadLocalDirs()
}

async function loadLocalDirs() {
  try {
    const r = await fetch('/api/ai/skills/local-dirs')
    const d = await r.json()
    localDirs.value = d.dirs || []
  } catch { /* ignore */ }
}

async function registerDir() {
  const path = localPath.value.trim()
  if (!path) { message.warning('请输入本地目录路径'); return }
  registeringDir.value = true
  try {
    const res = await fetch('/api/ai/skills/local-dir', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    })
    let d: any = {}
    try { d = await res.json() } catch { /* ignore */ }
    if (!res.ok || d.ok === false) { message.error(`注册失败: ${errOf(res, d)}`); return }
    message.success(`目录已注册，当前共 ${d.skill_count ?? 0} 个技能`)
    localPath.value = ''
    await Promise.all([loadLocalDirs(), loadSkills()])
  } catch { message.error('注册失败') }
  finally { registeringDir.value = false }
}

async function removeDir(path: string) {
  removingDir.value = path
  try {
    const res = await fetch('/api/ai/skills/local-dir', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    })
    let d: any = {}
    try { d = await res.json() } catch { /* ignore */ }
    if (!res.ok) { message.error(`移除失败: ${errOf(res, d)}`); return }
    message.success('目录已取消注册')
    await Promise.all([loadLocalDirs(), loadSkills()])
  } catch { message.error('移除失败') }
  finally { removingDir.value = '' }
}

async function importLocalContent() {
  const text = localContent.value.trim()
  if (!text) { message.warning('请粘贴 SKILL.md 文本'); return }
  importingLocal.value = true
  try {
    const res = await fetch('/api/ai/skill-store/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: text }),
    })
    let d: any = {}
    try { d = await res.json() } catch { /* ignore */ }
    if (!res.ok || d.ok === false) { message.error(`导入失败: ${errOf(res, d)}`); return }
    message.success(`「${d.name}」已导入（默认禁用，请确认后启用）`)
    localContent.value = ''
    await loadSkills()
  } catch { message.error('导入失败') }
  finally { importingLocal.value = false }
}

onMounted(loadSkills)
</script>

<template>
  <div>
    <n-divider />
    <div class="skills-header">
      <n-h3 style="margin:0">已加载技能 ({{ skills.length }})</n-h3>
      <n-space size="small">
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button size="small" quaternary :loading="rescanning" @click="rescanSkills">↻ 重扫</n-button>
          </template>
          重新扫描技能目录
        </n-tooltip>
        <n-button size="small" secondary type="success" @click="openStoreModal">从商店添加</n-button>
        <n-button size="small" secondary type="info" @click="openLocalModal">本地添加</n-button>
      </n-space>
    </div>
    <n-space vertical v-if="skills.length > 0">
      <n-card v-for="s in skills" :key="s.name" size="small"
        :style="{ opacity: s.enabled ? 1 : 0.5, transition: 'opacity 0.2s' }">
        <template #header>
          <span style="font-weight:600">{{ s.name }}</span>
          <n-tag size="tiny" :type="sourceTagType(s)" :bordered="false" style="margin-left:8px">
            {{ s.source_label || s.source }}
          </n-tag>
          <n-tag v-if="!s.enabled" size="tiny" type="warning" :bordered="false" style="margin-left:8px">已禁用</n-tag>
        </template>
        <template #header-extra>
          <n-space align="center" size="small">
            <n-popconfirm v-if="s.source !== 'builtin'"
              @positive-click="uninstallSkill(s.name)"
              positive-text="卸载" negative-text="取消">
              <template #trigger>
                <n-button size="tiny" quaternary type="error"
                  :loading="uninstalling === s.name">卸载</n-button>
              </template>
              确定卸载技能「{{ s.name }}」？文件将被删除。
            </n-popconfirm>
            <n-switch :value="s.enabled" size="small" :loading="switchingSkill === s.name"
              @update:value="(v: boolean) => toggleSkill(s, v)" />
          </n-space>
        </template>
        {{ s.description }}
      </n-card>
    </n-space>
    <n-empty v-else description="暂无技能" />

    <!-- ══ 商店 Modal ══ -->
    <n-modal v-model:show="showStoreModal" preset="card" title="从技能商店添加"
      style="width: 720px; max-width: 92vw">
      <n-spin :show="loadingPlatforms">
        <n-grid :cols="3" :x-gap="10" :y-gap="10" responsive="screen" item-responsive>
          <n-gi v-for="p in platforms" :key="p.id" span="3 m:1">
            <div class="platform-card" :class="{ active: selectedPlatform === p.id }"
              @click="selectedPlatform = p.id">
              <div class="platform-top">
                <span class="platform-name">{{ p.name }}</span>
                <n-tag size="tiny" :type="p.level === 'api' ? 'success' : 'default'" :bordered="false">
                  {{ p.grade }} 级 · {{ p.level === 'api' ? '系统内搜索' : '跳转浏览' }}
                </n-tag>
              </div>
              <div class="platform-desc">{{ p.description }}</div>
              <n-button size="tiny" quaternary @click.stop="openPlatform(p.url)">打开平台 ↗</n-button>
            </div>
          </n-gi>
        </n-grid>
      </n-spin>

      <n-divider style="margin: 14px 0" />

      <!-- skill.sh：系统内搜索 -->
      <div v-if="selectedPlatform === 'skillsh'">
        <n-input-group>
          <n-input v-model:value="searchQuery" placeholder="搜索技能，如 commit / translate …"
            clearable @keydown.enter="doSearch" />
          <n-button type="primary" :loading="searching" @click="doSearch">搜索</n-button>
        </n-input-group>
        <div style="margin-top:12px">
          <n-spin :show="searching">
            <n-alert v-if="searchError" type="warning" :bordered="false" style="margin-bottom:8px">
              {{ searchError }}
            </n-alert>
            <n-empty v-else-if="searchDone && searchResults.length === 0" size="small" description="未找到相关技能" />
            <n-space vertical v-if="searchResults.length > 0" size="small">
              <n-card v-for="item in searchResults" :key="item.ref || item.name" size="small">
                <template #header>
                  <span style="font-weight:600">{{ item.name }}</span>
                </template>
                <template #header-extra>
                  <n-button size="tiny" type="primary" secondary
                    :loading="installingRef === (item.ref || item.name)"
                    @click="installFromSearch(item)">安装</n-button>
                </template>
                <span class="result-desc">{{ item.description || item.ref }}</span>
              </n-card>
            </n-space>
          </n-spin>
        </div>
      </div>

      <!-- skillsmp / skillhub.cn：粘贴区 -->
      <div v-else>
        <n-alert type="info" :bordered="false" style="margin-bottom:8px">
          请先在浏览器打开「{{ currentPlatform?.name }}」，然后粘贴技能页链接（需含 GitHub 仓库信息）
          或 SKILL.md 全文内容，系统将自动识别并安装。
        </n-alert>
        <n-input v-model:value="pasteText" type="textarea" :rows="8"
          placeholder="粘贴技能页链接（如 https://github.com/owner/repo/path）&#10;或 SKILL.md 全文（以 --- 开头的 frontmatter 格式）" />
        <div style="margin-top:10px; text-align:right">
          <n-button type="primary" :loading="installingPaste" @click="installFromPaste">
            识别并安装
          </n-button>
        </div>
      </div>
    </n-modal>

    <!-- ══ 本地添加 Modal ══ -->
    <n-modal v-model:show="showLocalModal" preset="card" title="本地添加技能"
      style="width: 640px; max-width: 92vw">
      <n-h4 style="margin:4px 0 8px">① 注册本地目录</n-h4>
      <n-input-group>
        <n-input v-model:value="localPath" placeholder="输入目录路径（目录内需含 SKILL.md，可含子目录）" />
        <n-button type="primary" :loading="registeringDir" @click="registerDir">注册</n-button>
      </n-input-group>
      <div v-if="localDirs.length > 0" style="margin-top:10px">
        <n-space vertical size="small">
          <div v-for="dir in localDirs" :key="dir" class="local-dir-row">
            <n-ellipsis style="flex:1" :tooltip="true">{{ dir }}</n-ellipsis>
            <n-button size="tiny" quaternary type="error"
              :loading="removingDir === dir" @click="removeDir(dir)">移除</n-button>
          </div>
        </n-space>
      </div>
      <n-text v-else depth="3" style="font-size:12px">尚未注册任何本地目录</n-text>

      <n-divider style="margin:14px 0" />

      <n-h4 style="margin:4px 0 8px">② 粘贴 SKILL.md 文本导入</n-h4>
      <n-input v-model:value="localContent" type="textarea" :rows="7"
        placeholder="---&#10;name: my_skill&#10;description: 一句话描述&#10;---&#10;技能正文…" />
      <div style="margin-top:10px; text-align:right">
        <n-button type="primary" :loading="importingLocal" @click="importLocalContent">导入</n-button>
      </div>
    </n-modal>
  </div>
</template>

<style scoped>
.skills-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
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
  border-color: rgba(24, 160, 88, 0.6);
}
.platform-card.active {
  border-color: #18a058;
  background: rgba(24, 160, 88, 0.06);
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
.local-dir-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  border: 1px solid rgba(128, 128, 128, 0.2);
  border-radius: 6px;
  font-size: 13px;
}
</style>
