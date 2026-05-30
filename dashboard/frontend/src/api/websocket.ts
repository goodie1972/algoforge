// WebSocket 客户端 - 自动重连 + 指数退避
import type { WsMessage } from '@/types'

type MessageHandler = (msg: WsMessage) => void

class WebSocketClient {
  private ws: WebSocket | null = null
  private handlers: Map<string, Set<MessageHandler>> = new Map()
  private reconnectDelay = 1000
  private maxReconnectDelay = 30000
  private shouldReconnect = true
  private url = ''

  connect(url = `/ws`) {
    this.url = url
    this.shouldReconnect = true
    this._connect()
  }

  disconnect() {
    this.shouldReconnect = false
    this.ws?.close()
    this.ws = null
  }

  on(channel: string, handler: MessageHandler) {
    if (!this.handlers.has(channel)) {
      this.handlers.set(channel, new Set())
    }
    this.handlers.get(channel)!.add(handler)
    return () => this.handlers.get(channel)?.delete(handler)
  }

  off(channel: string, handler: MessageHandler) {
    this.handlers.get(channel)?.delete(handler)
  }

  private _connect() {
    if (!this.shouldReconnect) return

    this.ws = new WebSocket(this.url)

    this.ws.onopen = () => {
      this.reconnectDelay = 1000 // 重置重连延迟
    }

    this.ws.onmessage = (event) => {
      try {
        const msg: WsMessage = JSON.parse(event.data)
        const handlers = this.handlers.get(msg.channel)
        if (handlers) {
          handlers.forEach((h) => h(msg))
        }
        // 同时触发通配符监听
        const allHandlers = this.handlers.get('*')
        if (allHandlers) {
          allHandlers.forEach((h) => h(msg))
        }
      } catch {
        // ignore parse errors
      }
    }

    this.ws.onclose = () => {
      if (this.shouldReconnect) {
        setTimeout(() => this._connect(), this.reconnectDelay)
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay)
      }
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }
}

export const wsClient = new WebSocketClient()
