<script setup lang="ts">
import { ref, nextTick, onMounted, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '@/stores/chat'
import ChatMessage from './ChatMessage.vue'
import FortuneCat from './FortuneCat.vue'

const { t } = useI18n()
const emit = defineEmits<{ close: [PanelGeo] }>()
// 与启动按钮位置协同：打开时 launcher 传入按钮当前位置作为锚点
const props = defineProps<{ anchor?: { x: number; y: number } | null }>()
const chat = useChatStore()
const inputText = ref('')
const showSessions = ref(false)
const messagesContainer = ref<HTMLElement | null>(null)

// ── 浮动面板几何：拖动 / 调节大小 / localStorage 持久化 ──
const GEO_KEY = 'ai_panel_geometry'
const MIN_W = 320
const MIN_H = 400

interface PanelGeo { x: number; y: number; w: number; h: number }

function defaultGeo(): PanelGeo {
  const w = Math.min(420, window.innerWidth - 16)
  const h = Math.min(600, window.innerHeight - 16)
  return {
    x: Math.max(8, window.innerWidth - w - 24),
    y: Math.max(8, window.innerHeight - h - 24),
    w, h,
  }
}

// 尺寸限制在最小值与视口之间；位置至少保留 40px 可见区域
function clampGeo(g: PanelGeo): PanelGeo {
  const vw = window.innerWidth, vh = window.innerHeight
  const w = Math.max(MIN_W, Math.min(g.w || MIN_W, vw))
  const h = Math.max(MIN_H, Math.min(g.h || MIN_H, vh))
  const x = Math.max(-(w - 40), Math.min(g.x ?? 0, vw - 40))
  const y = Math.max(-(h - 40), Math.min(g.y ?? 0, vh - 40))
  return { x, y, w, h }
}

function loadGeo(): PanelGeo {
  try {
    const raw = localStorage.getItem(GEO_KEY)
    if (raw) {
      const g = JSON.parse(raw)
      if (['x', 'y', 'w', 'h'].every(k => typeof g[k] === 'number')) return clampGeo(g)
    }
  } catch { /* 数据损坏回退默认 */ }
  return defaultGeo()
}

// 初始几何：尺寸沿用自身记忆；位置优先按锚点（按钮位置）计算，缺失/损坏回退记忆位置
function initGeo(): PanelGeo {
  const saved = loadGeo()
  const a = props.anchor
  if (!a || typeof a.x !== 'number' || typeof a.y !== 'number') return saved
  // 面板右下角对齐按钮左上角外 12px（面板弹在按钮左上方）
  let x = a.x - 12 - saved.w
  let y = a.y - 12 - saved.h
  if (x < 0) x = a.x + 72    // 左侧放不下 → 翻转到按钮右侧
  if (y < 0) y = a.y + 72    // 上方放不下 → 翻转到按钮下方
  return clampGeo({ x, y, w: saved.w, h: saved.h })
}

const geo = ref<PanelGeo>(initGeo())
const dragging = ref(false)
const resizing = ref<'' | 'corner' | 'right' | 'bottom'>('')
const panelRef = ref<HTMLElement | null>(null)
let dragStart = { px: 0, py: 0, x: 0, y: 0 }
let resizeStart = { px: 0, py: 0, w: 0, h: 0 }

function saveGeo() {
  try { localStorage.setItem(GEO_KEY, JSON.stringify(geo.value)) } catch { /* ignore */ }
}

// ── 拖动（标题栏为手柄，Pointer Events + setPointerCapture）──
function onHeaderPointerDown(e: PointerEvent) {
  // 标题栏上的按钮（关闭/会话列表）按下时不触发拖动
  if ((e.target as HTMLElement).closest('button')) return
  dragging.value = true
  dragStart = { px: e.clientX, py: e.clientY, x: geo.value.x, y: geo.value.y }
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  e.preventDefault()
}

function onHeaderPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  const vw = window.innerWidth, vh = window.innerHeight
  const nx = dragStart.x + (e.clientX - dragStart.px)
  const ny = dragStart.y + (e.clientY - dragStart.py)
  geo.value.x = Math.max(-(geo.value.w - 40), Math.min(nx, vw - 40))
  geo.value.y = Math.max(-(geo.value.h - 40), Math.min(ny, vh - 40))
}

function onHeaderPointerUp(e: PointerEvent) {
  if (!dragging.value) return
  dragging.value = false
  saveGeo()
  try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId) } catch { /* ignore */ }
}

// ── 调节大小（右下角 / 右侧边 / 底边手柄）──
function onResizePointerDown(mode: 'corner' | 'right' | 'bottom', e: PointerEvent) {
  resizing.value = mode
  resizeStart = { px: e.clientX, py: e.clientY, w: geo.value.w, h: geo.value.h }
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  e.preventDefault()
  e.stopPropagation()
}

function onResizePointerMove(e: PointerEvent) {
  if (!resizing.value) return
  const vw = window.innerWidth, vh = window.innerHeight
  if (resizing.value !== 'bottom') {
    const maxW = Math.max(MIN_W, vw - geo.value.x)  // 右缘不超视口
    geo.value.w = Math.max(MIN_W, Math.min(resizeStart.w + (e.clientX - resizeStart.px), maxW))
  }
  if (resizing.value !== 'right') {
    const maxH = Math.max(MIN_H, vh - geo.value.y)  // 底缘不超视口
    geo.value.h = Math.max(MIN_H, Math.min(resizeStart.h + (e.clientY - resizeStart.py), maxH))
  }
}

function onResizePointerUp(e: PointerEvent) {
  if (!resizing.value) return
  resizing.value = ''
  saveGeo()
  try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId) } catch { /* ignore */ }
}

// 窗口尺寸变化时修正越界位置与尺寸
function onWindowResize() {
  geo.value = clampGeo(geo.value)
}

onMounted(async () => {
  window.addEventListener('resize', onWindowResize)
  await chat.fetchSessions()
  scrollToBottom()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onWindowResize)
})

const quickCommands = [
  { label: '行情研判', text: '结合当前指标和新闻，给我一个简短的行情研判' },
  { label: '持仓诊断', text: '分析我当前的持仓，是否有风险？给止盈止损建议' },
  { label: '新闻解读', text: '最近的重要黄金新闻有什么影响？' },
  { label: '策略表现', text: '最近哪个策略表现最好/最差？数据分析' },
  { label: '风险检查', text: '当前有什么风险需要注意的？' },
  { label: '今日总结', text: '帮我总结今天的交易情况' },
]

watch(() => chat.messages.length, () => {
  nextTick(scrollToBottom)
})
watch(() => chat.messages, () => {
  nextTick(scrollToBottom)
}, { deep: true })

function scrollToBottom() {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || chat.streaming) return
  inputText.value = ''
  await chat.sendMessage(text)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function handleQuickCommand(cmd: typeof quickCommands[0]) {
  if (chat.streaming) return
  inputText.value = ''
  chat.sendMessage(cmd.text)
}

async function handleNewSession() {
  await chat.createSession()
  showSessions.value = false
}

async function handleSelectSession(id: string) {
  await chat.selectSession(id)
  showSessions.value = false
}

async function handleDeleteSession(id: string, e: Event) {
  e.stopPropagation()
  await chat.deleteSession(id)
}

// 关闭：把最终几何上报给 launcher，供其锚定按钮位置（协同联动）
function handleClose() {
  emit('close', { x: geo.value.x, y: geo.value.y, w: geo.value.w, h: geo.value.h })
}
</script>

<template>
  <div ref="panelRef" class="ai-chat-panel" :class="{ 'is-active': dragging || resizing }"
    :style="{ left: geo.x + 'px', top: geo.y + 'px', width: geo.w + 'px', height: geo.h + 'px' }">
    <!-- 头部（拖拽手柄） -->
    <div class="chat-header"
      @pointerdown="onHeaderPointerDown" @pointermove="onHeaderPointerMove" @pointerup="onHeaderPointerUp">
      <div class="chat-header-left">
        <div class="chat-header-avatar"><FortuneCat :size="26" /></div>
        <div class="chat-header-info">
          <div class="chat-header-name">金探</div>
          <div class="chat-header-role">黄金交易分析师 · 在线</div>
        </div>
      </div>
      <div class="chat-header-right">
        <button class="chat-icon-btn" @click="handleClose" title="关闭">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
        <button class="chat-icon-btn" :class="{ active: showSessions }" @click="showSessions = !showSessions" title="会话列表">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- 会话列表 Drawer -->
    <Transition name="slide">
      <div v-if="showSessions" class="chat-sessions">
        <div class="chat-sessions-header">
          <span>会话历史</span>
          <button class="chat-new-btn" @click="handleNewSession">+ 新建</button>
        </div>
        <div class="chat-sessions-list">
          <div
            v-for="s in chat.sessions"
            :key="s.id"
            class="chat-session-item"
            :class="{ active: s.id === chat.currentSessionId }"
            @click="handleSelectSession(s.id)"
          >
            <span class="chat-session-title">{{ s.title }}</span>
            <span class="chat-session-count">{{ s.msg_count || 0 }}条</span>
            <button class="chat-session-del" @click="handleDeleteSession(s.id, $event)">✕</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 消息区域 -->
    <div ref="messagesContainer" class="chat-messages">
      <!-- 空状态 -->
      <div v-if="chat.messages.length === 0" class="chat-empty">
        <div class="chat-empty-avatar"><FortuneCat :size="32" /></div>
        <div class="chat-empty-title">你好，我是金探</div>
        <div class="chat-empty-subtitle">你的黄金交易分析师</div>
        <div class="chat-empty-desc">我可以实时查看你的持仓、账户、指标和新闻，随时问我。</div>
        <div class="chat-empty-hint">试试这些：</div>
        <div class="chat-empty-commands">
          <button v-for="cmd in quickCommands" :key="cmd.label" class="chat-empty-cmd" @click="handleQuickCommand(cmd)">
            {{ cmd.label }}
          </button>
        </div>
      </div>

      <!-- 消息列表 -->
      <template v-for="(msg, idx) in chat.messages" :key="idx">
        <ChatMessage
          :role="msg.role"
          :content="msg.content"
          :streaming="chat.streaming && idx === chat.messages.length - 1 && msg.role === 'assistant'"
          :tool-status="msg.toolStatus"
        />
      </template>

      <!-- 加载中 -->
      <div v-if="chat.streaming && chat.messages.length > 0 && chat.messages[chat.messages.length - 1].content === ''" class="chat-typing">
        <span class="chat-typing-dot"></span>
        <span class="chat-typing-dot"></span>
        <span class="chat-typing-dot"></span>
      </div>
    </div>

    <!-- 快捷命令栏 -->
    <div class="chat-quick">
      <button
        v-for="cmd in quickCommands"
        :key="cmd.label"
        class="chat-quick-btn"
        :disabled="chat.streaming"
        @click="handleQuickCommand(cmd)"
      >{{ cmd.label }}</button>
    </div>

    <!-- 输入区域 -->
    <div class="chat-input-area">
      <div class="chat-input-wrap">
        <textarea
          v-model="inputText"
          class="chat-input"
          :placeholder="chat.streaming ? '金探正在思考...' : '问金探任何交易问题...'"
          :disabled="chat.streaming"
          @keydown="handleKeydown"
        />
        <button class="chat-send-btn" :disabled="!inputText.trim() || chat.streaming" @click="handleSend">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- 调节大小手柄：右侧边 / 底边 / 右下角 -->
    <div class="resize-handle resize-handle--right"
      @pointerdown="onResizePointerDown('right', $event)" @pointermove="onResizePointerMove" @pointerup="onResizePointerUp"></div>
    <div class="resize-handle resize-handle--bottom"
      @pointerdown="onResizePointerDown('bottom', $event)" @pointermove="onResizePointerMove" @pointerup="onResizePointerUp"></div>
    <div class="resize-handle resize-handle--corner" :title="t('ai.chat_panel_resize_hint')"
      @pointerdown="onResizePointerDown('corner', $event)" @pointermove="onResizePointerMove" @pointerup="onResizePointerUp"></div>
  </div>
</template>

<style scoped>
.ai-chat-panel {
  position: fixed;
  z-index: 9999;
  min-width: 320px;
  min-height: 400px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px var(--shadow-heavy);
  transition: box-shadow 0.15s ease;
}
/* 拖动/缩放中的加强反馈 */
.ai-chat-panel.is-active {
  box-shadow: 0 28px 80px rgba(0, 0, 0, 0.7), 0 0 0 1px rgba(240, 185, 11, 0.3);
}

/* 头部 */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  cursor: move;
  user-select: none;
  touch-action: none;
}
.chat-header-left { display: flex; align-items: center; gap: 10px; }
.chat-header-avatar {
  width: 36px; height: 36px; border-radius: 50%;
  background: linear-gradient(135deg, #f0b90b, #d4a309);
  display: flex; align-items: center; justify-content: center;
  font-size: 16px;
}
.chat-header-name { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.chat-header-role { font-size: 11px; color: var(--text-muted); }
.chat-header-right { display: flex; gap: 4px; }
.chat-icon-btn {
  background: transparent; border: none; color: var(--text-muted);
  cursor: pointer; padding: 6px; border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
}
.chat-icon-btn:hover { background: var(--border-color); color: var(--text-primary); }
.chat-icon-btn.active { background: var(--border-color); color: #f0b90b; }

/* 会话列表 */
.chat-sessions {
  position: absolute;
  top: 61px; left: 0; bottom: 0;
  width: 200px;
  background: var(--bg-primary);
  border-right: 1px solid var(--border-color);
  z-index: 10;
  display: flex;
  flex-direction: column;
}
.chat-sessions-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 12px; border-bottom: 1px solid var(--border-color);
  font-size: 12px; color: var(--text-muted);
}
.chat-new-btn {
  background: rgba(240,185,11,0.1); border: 1px solid rgba(240,185,11,0.3);
  color: #f0b90b; font-size: 11px; padding: 2px 8px;
  border-radius: 4px; cursor: pointer;
}
.chat-new-btn:hover { background: rgba(240,185,11,0.2); }
.chat-sessions-list { flex: 1; overflow-y: auto; }
.chat-session-item {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 12px; cursor: pointer;
  border-bottom: 1px solid var(--border-color);
}
.chat-session-item:hover { background: var(--bg-secondary); }
.chat-session-item.active { background: var(--bg-secondary); border-left: 2px solid #f0b90b; }
.chat-session-title { flex: 1; font-size: 12px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-session-count { font-size: 10px; color: var(--text-muted); }
.chat-session-del {
  background: transparent; border: none; color: #484f58;
  cursor: pointer; font-size: 10px; padding: 2px;
}
.chat-session-del:hover { color: #f85149; }

/* 消息区域 */
.chat-messages {
  flex: 1; overflow-y: auto; padding: 16px;
  scroll-behavior: smooth;
}
.chat-messages::-webkit-scrollbar { width: 4px; }
.chat-messages::-webkit-scrollbar-thumb { background: #30363d; border-radius: 2px; }

/* 空状态 */
.chat-empty {
  display: flex; flex-direction: column; align-items: center;
  padding: 40px 20px; text-align: center;
}
.chat-empty-avatar {
  width: 48px; height: 48px; border-radius: 50%;
  background: linear-gradient(135deg, #f0b90b, #d4a309);
  display: flex; align-items: center; justify-content: center;
  font-size: 24px; margin-bottom: 16px;
}
.chat-empty-title { font-size: 16px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
.chat-empty-subtitle { font-size: 13px; color: var(--text-muted); margin-bottom: 16px; }
.chat-empty-desc { font-size: 12px; color: var(--text-muted); margin-bottom: 20px; line-height: 1.6; }
.chat-empty-hint { font-size: 12px; color: var(--text-muted); margin-bottom: 8px; }
.chat-empty-commands { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; max-height: 120px; overflow-y: auto; }
.chat-empty-cmd {
  background: rgba(240,185,11,0.08); border: 1px solid rgba(240,185,11,0.2);
  color: #f0b90b; font-size: 11px; padding: 4px 10px;
  border-radius: 12px; cursor: pointer;
}
.chat-empty-cmd:hover { background: rgba(240,185,11,0.15); }

/* 快捷命令栏 */
.chat-quick {
  display: flex; flex-direction: row; gap: 4px;
  padding: 4px 8px; border-top: 1px solid var(--border-color);
  background: var(--bg-secondary); flex-wrap: nowrap; overflow: hidden;
}
.chat-quick-btn {
  background: rgba(240,185,11,0.08); border: 1px solid rgba(240,185,11,0.2);
  color: #f0b90b; font-size: 11px; padding: 2px 6px;
  border-radius: 4px; cursor: pointer; white-space: nowrap;
  flex-shrink: 1; min-width: 0;
  transition: background 0.12s ease;
}
.chat-quick-btn:hover:not(:disabled) { background: rgba(240,185,11,0.18); }
.chat-quick-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* 输入区域 */
.chat-input-area {
  padding: 8px 12px; border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
}
.chat-input-wrap {
  position: relative;
}
.chat-input {
  width: 100%; background: var(--input-bg); border: 1px solid var(--border-color);
  color: var(--text-primary); border-radius: 8px; padding: 8px 44px 8px 12px;
  font-size: 13px; resize: none; outline: none;
  max-height: 120px;
  font-family: inherit;
}
.chat-input:focus { border-color: rgba(240,185,11,0.5); }
.chat-input::placeholder { color: var(--text-muted); }
.chat-send-btn {
  position: absolute; right: 4px; bottom: 4px;
  width: 36px; height: 36px; border-radius: 8px;
  background: linear-gradient(135deg, #f0b90b, #d4a309);
  border: none; color: var(--bg-primary); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.chat-send-btn:hover:not(:disabled) { opacity: 0.9; }
.chat-send-btn:disabled { opacity: 0.3; cursor: not-allowed; }

/* 打字动画 */
.chat-typing {
  display: flex; gap: 4px; padding: 8px 14px;
}
.chat-typing-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: #f0b90b; animation: typing-bounce 0.6s infinite alternate;
}
.chat-typing-dot:nth-child(2) { animation-delay: 0.2s; }
.chat-typing-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing-bounce {
  0% { transform: translateY(0); opacity: 0.4; }
  100% { transform: translateY(-4px); opacity: 1; }
}

/* Drawer 动画 */
.slide-enter-active, .slide-leave-active {
  transition: transform 0.2s ease;
}
.slide-enter-from, .slide-leave-to {
  transform: translateX(-100%);
}

/* 调节大小手柄 */
.resize-handle {
  position: absolute;
  z-index: 20;
  touch-action: none;
}
.resize-handle--right {
  top: 70px; right: 0; bottom: 16px; width: 5px;
  cursor: ew-resize;
}
.resize-handle--bottom {
  left: 12px; right: 16px; bottom: 0; height: 5px;
  cursor: ns-resize;
}
.resize-handle--corner {
  right: 0; bottom: 0; width: 18px; height: 18px;
  cursor: nwse-resize;
}
.resize-handle--corner::after {
  content: '';
  position: absolute; right: 5px; bottom: 5px;
  width: 8px; height: 8px;
  border-right: 2px solid #484f58;
  border-bottom: 2px solid #484f58;
  border-bottom-right-radius: 2px;
  transition: border-color 0.15s ease;
}
.resize-handle--corner:hover::after,
.ai-chat-panel.is-active .resize-handle--corner::after {
  border-color: #f0b90b;
}
</style>
