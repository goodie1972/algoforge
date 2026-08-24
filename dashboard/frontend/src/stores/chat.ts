/**
 * AI 聊天 Pinia Store — 管理会话、消息、SSE 流式接收
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

const http = axios.create({ baseURL: '/api' })

interface ChatSession {
  id: string
  title: string
  created_at: string
  updated_at?: string
  msg_count?: number
}

interface ChatMessage {
  id?: number
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at?: string
  /** 工具调用状态（SSE tool 事件，仅流式期间展示） */
  toolStatus?: string
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const loading = ref(false)
  const streaming = ref(false)
  const error = ref<string | null>(null)

  const currentSession = computed(() =>
    sessions.value.find(s => s.id === currentSessionId.value)
  )

  // ── 会话管理 ──────────────────────────────

  async function fetchSessions() {
    try {
      const { data } = await http.get('/ai/sessions')
      sessions.value = data.sessions || []
      // 如果没有当前会话且有会话列表，选第一个
      if (!currentSessionId.value && sessions.value.length > 0) {
        await selectSession(sessions.value[0].id)
      }
    } catch (e) {
      console.error('[Chat] fetchSessions error:', e)
    }
  }

  async function createSession(title = '新会话'): Promise<string> {
    try {
      const { data } = await http.post('/ai/sessions', { title })
      sessions.value.unshift(data)
      currentSessionId.value = data.id
      messages.value = []
      return data.id
    } catch (e) {
      console.error('[Chat] createSession error:', e)
      throw e
    }
  }

  async function selectSession(sessionId: string) {
    currentSessionId.value = sessionId
    try {
      const { data } = await http.get(`/ai/sessions/${sessionId}/messages`)
      messages.value = data.messages || []
    } catch (e) {
      console.error('[Chat] selectSession error:', e)
      messages.value = []
    }
  }

  async function deleteSession(sessionId: string) {
    try {
      await http.delete(`/ai/sessions/${sessionId}`)
      sessions.value = sessions.value.filter(s => s.id !== sessionId)
      if (currentSessionId.value === sessionId) {
        currentSessionId.value = null
        messages.value = []
        if (sessions.value.length > 0) {
          await selectSession(sessions.value[0].id)
        }
      }
    } catch (e) {
      console.error('[Chat] deleteSession error:', e)
    }
  }

  // ── 发送消息（SSE 流式） ──────────────────

  async function sendMessage(text: string) {
    if (!text.trim() || streaming.value) return

    // 确保有会话
    if (!currentSessionId.value) {
      const sid = await createSession()
      currentSessionId.value = sid
    }

    // 添加用户消息到 UI
    messages.value.push({ role: 'user', content: text })

    // 添加空的 AI 消息占位（流式填充）
    const aiMsgIndex = messages.value.length
    messages.value.push({ role: 'assistant', content: '' })

    streaming.value = true
    error.value = null

    try {
      const resp = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: currentSessionId.value,
          message: text,
        }),
      })

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`)
      }

      const reader = resp.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const data = JSON.parse(line.slice(6))
            if (data.tool) {
              // 工具调用状态：后到的覆盖先到的，不影响 content 累积
              messages.value[aiMsgIndex].toolStatus = data.tool
            }
            if (data.content) {
              messages.value[aiMsgIndex].content += data.content
            }
            if (data.done) {
              if (data.message_id) {
                messages.value[aiMsgIndex].id = data.message_id
              }
              messages.value[aiMsgIndex].toolStatus = ''  // 流结束，清空工具状态
              if (data.error) {
                error.value = data.content
              }
            }
          } catch {
            // ignore parse errors
          }
        }
      }
      // 刷新会话列表（更新 msg_count 和 updated_at）
      await fetchSessions()
    } catch (e: any) {
      console.error('[Chat] sendMessage error:', e)
      error.value = e.message
      messages.value[aiMsgIndex].toolStatus = ''
      messages.value[aiMsgIndex].content =
        `⚠️ 调用失败: ${e.message || '未知错误'}`
    } finally {
      streaming.value = false
    }
  }

  return {
    sessions,
    currentSessionId,
    currentSession,
    messages,
    loading,
    streaming,
    error,
    fetchSessions,
    createSession,
    selectSession,
    deleteSession,
    sendMessage,
  }
})
