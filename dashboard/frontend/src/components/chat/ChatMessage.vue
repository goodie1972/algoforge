<script setup lang="ts">
import { computed } from 'vue'
import FortuneCat from './FortuneCat.vue'

const props = defineProps<{
  role: 'user' | 'assistant' | 'system'
  content: string
  streaming?: boolean
  /** 工具调用状态（流式期间由后端 tool 事件驱动） */
  toolStatus?: string
}>()

const isUser = computed(() => props.role === 'user')
const isAI = computed(() => props.role === 'assistant')

// 简易 Markdown 渲染：加粗、列表、表格、代码块
const renderedContent = computed(() => {
  let html = props.content
  // 代码块
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre class="chat-code-block"><code>${_escapeHtml(code.trim())}</code></pre>`
  })
  // 行内代码
  html = html.replace(/`([^`]+)`/g, '<code class="chat-inline-code">$1</code>')
  // 加粗
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  // 标题
  html = html.replace(/^### (.+)$/gm, '<div class="chat-h3">$1</div>')
  html = html.replace(/^## (.+)$/gm, '<div class="chat-h2">$1</div>')
  // 无序列表
  html = html.replace(/^- (.+)$/gm, '<div class="chat-li">• $1</div>')
  // 有序列表
  html = html.replace(/^\d+\. (.+)$/gm, (_, text) => `<div class="chat-li">${text}</div>`)
  // 换行
  html = html.replace(/\n/g, '<br/>')
  return html
})

const htmlContent = computed(() => {
  const cursor = props.streaming ? '<span class="chat-cursor">▊</span>' : ''
  return renderedContent.value + cursor
})

function _escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}
</script>

<template>
  <div class="chat-message" :class="{ 'chat-message--user': isUser, 'chat-message--ai': isAI }">
    <div v-if="isAI" class="chat-avatar">
      <FortuneCat :size="26" />
    </div>
    <div class="chat-bubble" :class="{ 'chat-bubble--user': isUser, 'chat-bubble--ai': isAI }">
      <div v-if="isAI && toolStatus" class="chat-tool-status">🔧 {{ toolStatus }}</div>
      <div
        v-if="isAI"
        class="chat-content"
        v-html="htmlContent"
      ></div>
      <div v-else class="chat-content">{{ content }}</div>
    </div>
    <div v-if="isUser" class="chat-avatar">
      <span class="chat-avatar-icon">👤</span>
    </div>
  </div>
</template>

<style scoped>
.chat-message {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  align-items: flex-start;
}
.chat-message--user {
  flex-direction: row-reverse;
}
.chat-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.chat-avatar-icon {
  font-size: 18px;
}
.chat-bubble {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}
.chat-bubble--user {
  background: rgba(240, 185, 11, 0.15);
  color: #e6edf3;
  border-radius: 12px 12px 4px 12px;
}
.chat-bubble--ai {
  background: #1c2333;
  color: #e6edf3;
  border-radius: 12px 12px 12px 4px;
  border-left: 3px solid #f0b90b;
}
.chat-content {
  text-align: left;
}
.chat-tool-status {
  font-size: 11px;
  color: #7d8590;
  margin-bottom: 4px;
  opacity: 0.85;
}
.chat-cursor {
  display: inline-block;
  animation: blink 0.8s infinite;
  color: #f0b90b;
}
@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
:deep(.chat-h2) { font-size: 14px; font-weight: 600; margin: 8px 0 4px; color: #f0b90b; }
:deep(.chat-h3) { font-size: 13px; font-weight: 600; margin: 6px 0 3px; color: #f0b90b; }
:deep(.chat-li) { padding-left: 12px; margin: 2px 0; }
:deep(.chat-code-block) {
  background: #0d1117;
  padding: 8px 12px;
  border-radius: 6px;
  margin: 6px 0;
  overflow-x: auto;
  font-size: 12px;
}
:deep(.chat-inline-code) {
  background: rgba(240, 185, 11, 0.1);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 12px;
}
:deep(strong) { color: #f0b90b; }
:deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; }
:deep(th), :deep(td) { border: 1px solid #333; padding: 4px 8px; font-size: 12px; }
:deep(th) { background: rgba(240, 185, 11, 0.1); }
</style>
