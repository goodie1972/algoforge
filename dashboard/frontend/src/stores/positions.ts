import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getPositions, closePosition, modifyPosition } from '@/api/client'
import type { Position } from '@/types'

export const usePositionStore = defineStore('positions', () => {
  const items = ref<Position[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const totalProfit = computed(() => items.value.reduce((s, p) => s + p.profit, 0))
  const longCount = computed(() => items.value.filter(p => p.order_type === 'OP_BUY' || p.order_type === 'BUY').length)
  const shortCount = computed(() => items.value.filter(p => p.order_type === 'OP_SELL' || p.order_type === 'SELL').length)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      items.value = await getPositions()
    } catch (e: any) {
      error.value = e?.message || '获取持仓失败'
    } finally {
      loading.value = false
    }
  }

  function updateFromWs(data: Position[]) {
    items.value = data
    error.value = null
  }

  async function close(ticket: number) {
    try {
      await closePosition(ticket)
      // 立即本地移除，不等 WS/5s 轮询（消除"平仓后仍显示旧持仓"的错觉）
      items.value = items.value.filter(p => String(p.ticket) !== String(ticket))
      await fetch()
    } catch (e: any) {
      const status = e?.response?.status
      if (status === 404) {
        // 订单已不存在：本地同步移除 + 抛出标记错误，由调用方提示友好文案
        items.value = items.value.filter(p => String(p.ticket) !== String(ticket))
        throw Object.assign(new Error('NOT_FOUND'), { notFound: true })
      }
      throw e
    }
  }

  async function modify(ticket: number, sl?: number, tp?: number) {
    await modifyPosition(ticket, sl, tp)
    await fetch()
  }

  return { items, loading, error, totalProfit, longCount, shortCount, fetch, updateFromWs, close, modify }
})
