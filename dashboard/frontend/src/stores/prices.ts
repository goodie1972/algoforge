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

  async function fetchCandles(timeframe = 'H1', count = 500) {
    loading.value = true
    try {
      candles.value = await getCandles(timeframe, count)
    } catch { /* ignore */ }
    finally { loading.value = false }
  }

  /** 轻量刷新：只拉最后 N 根 K 线（用于定时轮询），更新 candles[] 尾部 */
  async function fetchLatestCandles(timeframe = 'H1', count = 10) {
    try {
      const data = await getCandles(timeframe, count)
      if (data.length === 0) return data
      // 替换末尾对应条数，处理新蜡烛追加
      for (let i = 0; i < data.length; i++) {
        const idx = candles.value.length - count + i
        if (idx >= 0 && idx < candles.value.length) {
          candles.value[idx] = data[i]
        } else {
          candles.value.push(data[i])
        }
      }
      return data
    } catch { return [] }
  }

  return { bid, ask, spread, candles, midPrice, loading, updateTick, fetchPrice, fetchCandles, fetchLatestCandles }
})
