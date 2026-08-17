<script setup lang="ts">
import { ref, nextTick, onMounted, watch, onBeforeUnmount } from 'vue'
import { useChatStore } from '@/stores/chat'
import ChatMessage from './ChatMessage.vue'

const emit = defineEmits<{ close: [] }>()
const chat = useChatStore()
const inputText = ref('')
const showSessions = ref(false)
const messagesContainer = ref<HTMLElement | null>(null)

// 拖拽
const posX = ref(window.innerWidth - 460)
const posY = ref(window.innerHeight - 660)
const dragging = ref(false)
const dragOffset = ref({ x: 0, y: 0 })
const panelRef = ref<HTMLElement | null>(null)

function onHeaderMouseDown(e: MouseEvent) {
  dragging.value = true
  dragOffset.value = { x: e.clientX - posX.value, y: e.clientY - posY.value }
  e.preventDefault()
}

function onMouseMove(e: MouseEvent) {
  if (!dragging.value) return
  posX.value = Math.max(0, Math.min(window.innerWidth - 420, e.clientX - dragOffset.value.x))
  posY.value = Math.max(0, Math.min(window.innerHeight - 200, e.clientY - dragOffset.value.y))
}

function onMouseUp() {
  dragging.value = false
}

onMounted(() => {
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
  chat.fetchSessions()
  scrollToBottom()
})

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
})

const quickCommands = [
  { icon: '📊', label: '行情研判', text: '结合当前指标和新闻，给我一个简短的行情研判' },
  { icon: '💰', label: '持仓诊断', text: '分析我当前的持仓，是否有风险？给止盈止损建议' },
  { icon: '📰', label: '新闻解读', text: '最近的重要黄金新闻有什么影响？' },
  { icon: '📋', label: '策略表现', text: '最近哪个策略表现最好/最差？数据分析' },
  { icon: '⚠️', label: '风险检查', text: '当前有什么风险需要注意的？' },
  { icon: '📅', label: '今日总结', text: '帮我总结今天的交易情况' },
]

onMounted(async () => {
  await chat.fetchSessions()
  scrollToBottom()
})

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
</script>

<template>
  <div ref="panelRef" class="ai-chat-panel" :style="{ left: posX + 'px', top: posY + 'px', cursor: dragging ? 'grabbing' : undefined }">
    <!-- 头部（拖拽手柄） -->
    <div class="chat-header" @mousedown="onHeaderMouseDown" style="cursor: grab; user-select: none;">
      <div class="chat-header-left">
        <div class="chat-header-avatar">🟡</div>
        <div class="chat-header-info">
          <div class="chat-header-name">金探</div>
          <div class="chat-header-role">黄金交易分析师 · 在线</div>
        </div>
      </div>
      <div class="chat-header-right">
        <button class="chat-icon-btn" @click="emit('close')" title="关闭">
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
        <div class="chat-empty-avatar">🟡</div>
        <div class="chat-empty-title">你好，我是金探</div>
        <div class="chat-empty-subtitle">你的黄金交易分析师</div>
        <div class="chat-empty-desc">我可以实时查看你的持仓、账户、指标和新闻，随时问我。</div>
        <div class="chat-empty-hint">试试这些：</div>
        <div class="chat-empty-commands">
          <button v-for="cmd in quickCommands" :key="cmd.label" class="chat-empty-cmd" @click="handleQuickCommand(cmd)">
            {{ cmd.icon }} {{ cmd.label }}
          </button>
        </div>
      </div>

      <!-- 消息列表 -->
      <template v-for="(msg, idx) in chat.messages" :key="idx">
        <ChatMessage
          :role="msg.role"
          :content="msg.content"
          :streaming="chat.streaming && idx === chat.messages.length - 1 && msg.role === 'assistant'"
        />
      </template>

      <!-- 加载中 -->
      <div v-if="chat.streaming && chat.messages.length > 0 && chat.messages[chat.messages.length - 1].content === ''" class="chat-typing">
        <span class="chat-typing-dot"></span>
        <span class="chat-typing-dot"></span>
        <span class="chat-typing-dot"></span>
      </div>
    </div>

    <!-- 快捷指令栏 -->
    <div v-if="chat.messages.length > 0" class="chat-quick">
      <button
        v-for="cmd in quickCommands"
        :key="cmd.label"
        class="chat-quick-btn"
        :disabled="chat.streaming"
        @click="handleQuickCommand(cmd)"
      >
        {{ cmd.icon }} {{ cmd.label }}
      </button>
    </div>

    <!-- 输入区域 -->
    <div class="chat-input-area">
      <textarea
        v-model="inputText"
        class="chat-input"
        :placeholder="chat.streaming ? '金探正在思考...' : '问金探任何交易问题...'"
        :disabled="chat.streaming"
        @keydown="handleKeydown"
        rows="1"
      />
      <button class="chat-send-btn" :disabled="!inputText.trim() || chat.streaming" @click="handleSend">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.ai-chat-panel {
  position: fixed;
  width: 420px;
  max-width: 90vw;
  height: 600px;
  max-height: 80vh;
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

/* 头部 */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #21262d;
  background: #161b22;
}
.chat-header-left { display: flex; align-items: center; gap: 10px; }
.chat-header-avatar {
  width: 36px; height: 36px; border-radius: 50%;
  background: linear-gradient(135deg, #f0b90b, #d4a309);
  display: flex; align-items: center; justify-content: center;
  font-size: 16px;
}
.chat-header-name { font-size: 14px; font-weight: 600; color: #e6edf3; }
.chat-header-role { font-size: 11px; color: #7d8590; }
.chat-header-right { display: flex; gap: 4px; }
.chat-icon-btn {
  background: transparent; border: none; color: #7d8590;
  cursor: pointer; padding: 6px; border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
}
.chat-icon-btn:hover { background: #21262d; color: #e6edf3; }
.chat-icon-btn.active { background: #21262d; color: #f0b90b; }

/* 会话列表 */
.chat-sessions {
  position: absolute;
  top: 61px; left: 0; bottom: 0;
  width: 200px;
  background: #0d1117;
  border-right: 1px solid #21262d;
  z-index: 10;
  display: flex;
  flex-direction: column;
}
.chat-sessions-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 12px; border-bottom: 1px solid #21262d;
  font-size: 12px; color: #7d8590;
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
  border-bottom: 1px solid #161b22;
}
.chat-session-item:hover { background: #161b22; }
.chat-session-item.active { background: #161b22; border-left: 2px solid #f0b90b; }
.chat-session-title { flex: 1; font-size: 12px; color: #e6edf3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-session-count { font-size: 10px; color: #7d8590; }
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
.chat-empty-title { font-size: 16px; font-weight: 600; color: #e6edf3; margin-bottom: 4px; }
.chat-empty-subtitle { font-size: 13px; color: #7d8590; margin-bottom: 16px; }
.chat-empty-desc { font-size: 12px; color: #7d8590; margin-bottom: 20px; line-height: 1.6; }
.chat-empty-hint { font-size: 12px; color: #7d8590; margin-bottom: 8px; }
.chat-empty-commands { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
.chat-empty-cmd {
  background: rgba(240,185,11,0.08); border: 1px solid rgba(240,185,11,0.2);
  color: #f0b90b; font-size: 11px; padding: 4px 10px;
  border-radius: 12px; cursor: pointer;
}
.chat-empty-cmd:hover { background: rgba(240,185,11,0.15); }

/* 快捷指令 */
.chat-quick {
  display: flex; gap: 6px; padding: 6px 12px;
  overflow-x: auto; border-top: 1px solid #21262d;
}
.chat-quick::-webkit-scrollbar { display: none; }
.chat-quick-btn {
  background: rgba(240,185,11,0.08); border: 1px solid rgba(240,185,11,0.2);
  color: #f0b90b; font-size: 11px; padding: 4px 10px;
  border-radius: 12px; cursor: pointer; white-space: nowrap;
}
.chat-quick-btn:hover:not(:disabled) { background: rgba(240,185,11,0.15); }
.chat-quick-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* 输入区域 */
.chat-input-area {
  display: flex; align-items: flex-end; gap: 8px;
  padding: 10px 12px; border-top: 1px solid #21262d;
  background: #161b22;
}
.chat-input {
  flex: 1; background: #0d1117; border: 1px solid #21262d;
  color: #e6edf3; border-radius: 8px; padding: 8px 12px;
  font-size: 13px; resize: none; outline: none;
  min-height: 40px; max-height: 120px;
  font-family: inherit;
}
.chat-input:focus { border-color: rgba(240,185,11,0.5); }
.chat-input::placeholder { color: #484f58; }
.chat-send-btn {
  width: 36px; height: 36px; border-radius: 8px;
  background: linear-gradient(135deg, #f0b90b, #d4a309);
  border: none; color: #0d1117; cursor: pointer;
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
</style>
