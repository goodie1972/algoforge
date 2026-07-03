import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getPrice } from '@/api/client'
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
      const resp = await fetch(`/api/market/candles?timeframe=${timeframe}&count=${count}`)
      const data: Candle[] = await resp.json()
      if (data && data.length > 0) {
        candles.value = data
      } else {
        // 返回空数据时清空旧图（避免不同周期显示相同 K 线）
        candles.value = []
      }
    } catch {
      // 请求失败时清空旧图（避免残留上一周期数据）
      candles.value = []
    }
    finally { loading.value = false }
  }

  /** 轻量刷新：只拉最后 N 根 K 线（用于定时轮询），按时间戳匹配更新 */
  async function fetchLatestCandles(timeframe = 'H1', count = 10) {
    try {
      const resp = await fetch(`/api/market/candles?timeframe=${timeframe}&count=${count}`)
      const data: Candle[] = await resp.json()
      if (data.length === 0) return data
      // 按时间戳匹配更新，新蜡烛追加到尾部
      const timeMap = new Map(candles.value.map(c => [c.time, true]))
      let added = 0
      for (const c of data) {
        if (timeMap.has(c.time)) {
          // 更新已有蜡烛
          const idx = candles.value.findIndex(x => x.time === c.time)
          if (idx >= 0) candles.value[idx] = c
        } else {
          // 新蜡烛，追加
          candles.value.push(c)
          timeMap.set(c.time, true)
          added++
        }
      }
      // 如果追加了新蜡烛，裁剪旧数据防止无限膨胀
      if (added > 0 && candles.value.length > 1000) {
        candles.value.splice(0, added)
      }
      return data
    } catch { return [] }
  }

  return { bid, ask, spread, candles, midPrice, loading, updateTick, fetchPrice, fetchCandles, fetchLatestCandles }
})
