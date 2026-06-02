import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getTradeHistory } from '@/api/client'
import type { ClosedTrade } from '@/types'

export const useTradeStore = defineStore('trades', () => {
  const items = ref<ClosedTrade[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetch(limit = 100) {
    loading.value = true
    error.value = null
    try {
      items.value = await getTradeHistory(limit)
    } catch (e: any) {
      error.value = e?.message || '获取历史成交失败'
    } finally {
      loading.value = false
    }
  }

  function $reset() {
    items.value = []
    loading.value = false
    error.value = null
  }

  return { items, loading, error, fetch, $reset }
})
