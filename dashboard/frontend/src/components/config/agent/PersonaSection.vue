<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'

const message = useMessage()
const MAX_CHARS = 2000

const soul = ref('')
const memory = ref('')
const saving = ref(false)

const soulCount = computed(() => soul.value.length)
const memoryCount = computed(() => memory.value.length)
const soulOver = computed(() => soulCount.value > MAX_CHARS)
const memoryOver = computed(() => memoryCount.value > MAX_CHARS)
const canSave = computed(() => !soulOver.value && !memoryOver.value && !saving.value)

function countClass(count: number) {
  if (count > MAX_CHARS) return 'count-error'
  if (count >= MAX_CHARS * 0.9) return 'count-warn'
  return 'count-normal'
}

async function loadPersona() {
  try {
    const r = await fetch('/api/ai/persona')
    const d = await r.json()
    soul.value = d.soul || ''
    memory.value = d.memory || ''
  } catch (e) { /* ignore */ }
}

async function savePersona() {
  if (!canSave.value) return
  saving.value = true
  try {
    const r = await fetch('/api/ai/persona', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ soul: soul.value, memory: memory.value }),
    })
    const d = await r.json().catch(() => ({}))
    if (!r.ok || d.error || d.detail) {
      message.error(d.error || d.detail || `保存失败 (${r.status})`)
      return
    }
    message.success('人设已保存')
  } catch (e: any) {
    message.error(`保存失败: ${e?.message || e}`)
  } finally {
    saving.value = false
  }
}

// ── 导出：下载 soul.md / memory.md ──────────────────────
function downloadFile(filename: string, text: string) {
  const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
function exportFiles() {
  downloadFile('soul.md', soul.value)
  downloadFile('memory.md', memory.value)
  message.success('已导出 soul.md 与 memory.md')
}

// ── 导入：选择 .md 文件读取文本 ─────────────────────────
const fileInput = ref<HTMLInputElement>()
function importFiles() {
  fileInput.value?.click()
}
function onFilesSelected(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (!files.length) return
  let handled = 0
  for (const file of files) {
    const name = file.name.toLowerCase()
    const target = name.includes('soul') ? 'soul' : name.includes('memory') ? 'memory' : null
    if (!target) continue
    const reader = new FileReader()
    reader.onload = () => {
      const text = String(reader.result ?? '')
      if (text.length > MAX_CHARS) {
        message.warning(`${file.name} 共 ${text.length} 字，超过 ${MAX_CHARS} 字限制，已填入但无法保存`)
      }
      if (target === 'soul') soul.value = text
      else memory.value = text
      message.success(`已导入 ${file.name}`)
    }
    reader.readAsText(file, 'utf-8')
    handled++
  }
  if (!handled) message.warning('请选择文件名包含 soul 或 memory 的 .md 文件')
  input.value = ''
}

onMounted(loadPersona)
</script>

<template>
  <n-card size="small" :bordered="true">
    <template #header>
      <span>AI 人设</span>
    </template>
    <n-space vertical :size="14">
      <!-- 基础设定 Soul -->
      <div class="persona-block">
        <div class="block-header">
          <span class="block-title">基础设定（Soul）</span>
          <span class="char-count" :class="countClass(soulCount)">{{ soulCount }} / {{ MAX_CHARS }}</span>
        </div>
        <n-input
          v-model:value="soul"
          type="textarea"
          placeholder="身份 / 能力 / 风格 / 限制（占 system prompt 首位）"
          :rows="10"
          :maxlength="MAX_CHARS + 100"
          :status="soulOver ? 'error' : undefined"
        />
        <div v-if="soulOver" class="limit-warning">⚠ 基础设定超过 {{ MAX_CHARS }} 字限制，无法保存</div>
      </div>

      <!-- 日常记忆 Memory -->
      <div class="persona-block">
        <div class="block-header">
          <span class="block-title">日常记忆（Memory）</span>
          <span class="char-count" :class="countClass(memoryCount)">{{ memoryCount }} / {{ MAX_CHARS }}</span>
        </div>
        <n-input
          v-model:value="memory"
          type="textarea"
          placeholder="使用过程中的记忆沉淀，会话时冻结注入"
          :rows="6"
          :maxlength="MAX_CHARS + 100"
          :status="memoryOver ? 'error' : undefined"
        />
        <div v-if="memoryOver" class="limit-warning">⚠ 日常记忆超过 {{ MAX_CHARS }} 字限制，无法保存</div>
      </div>

      <n-space>
        <n-button size="small" type="primary" color="#f0b90b" style="color:#1e2329" :disabled="!canSave" :loading="saving" @click="savePersona">
          保存人设
        </n-button>
        <n-button size="small" @click="exportFiles">导出 soul.md / memory.md</n-button>
        <n-button size="small" @click="importFiles">导入 .md 文件</n-button>
        <input
          ref="fileInput"
          type="file"
          accept=".md,.markdown,text/markdown,text/plain"
          multiple
          style="display:none"
          @change="onFilesSelected"
        />
      </n-space>
    </n-space>
  </n-card>
</template>

<style scoped>
.persona-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.block-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}
.block-title {
  font-weight: 600;
  font-size: 13px;
  color: #f0b90b;
}
.char-count {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.count-normal {
  color: rgba(255, 255, 255, 0.45);
}
.count-warn {
  color: #f2a33c;
  font-weight: 600;
}
.count-error {
  color: #e8808a;
  font-weight: 700;
}
.limit-warning {
  font-size: 12px;
  color: #e8808a;
}
</style>
