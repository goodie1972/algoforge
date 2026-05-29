import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getPrice, getCandles } from '@/api/client'
import type { Candle } from '@/types'

export const usePriceStore = defineStore('prices', () => {
  const bid = ref(0)
  const ask = ref(0)
  const spread = ref(0)
  const candles = ref<Candle[]>([])
  const loading = ref(false)

  const midPrice = computed(() => (bid.value + ask.value) / 2)

  function updateTick(b: number, a: number) {
    bid.value = b
    ask.value = a
    spread.value = parseFloat((a - b).toFixed(2))
  }

  async function fetchPrice() {
    try {
      const data = await getPrice()
      updateTick(data.bid, data.ask)
    } catch { /* ignore polling errors */ }
  }

  async function fetchCandles(timeframe = 'H1', count = 100) {
    loading.value = true
    try {
      candles.value = await getCandles(timeframe, count)
    } catch { /* ignore */ }
    finally { loading.value = false }
  }

  return { bid, ask, spread, candles, midPrice, loading, updateTick, fetchPrice, fetchCandles }
})
