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

  let lastMoreBefore = 0  // 历史滚动加载防抖：同一 before 不重复请求

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

  async function fetchCandles(timeframe = 'H1', count = 2000) {
    loading.value = true
    lastMoreBefore = 0  // 切换周期后重置历史加载防抖
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
      // 按时间戳匹配更新，新蜡烛追加到尾部（不裁头部，避免删掉已加载的历史）
      const timeMap = new Map(candles.value.map(c => [c.time, true]))
      for (const c of data) {
        if (timeMap.has(c.time)) {
          // 更新已有蜡烛
          const idx = candles.value.findIndex(x => x.time === c.time)
          if (idx >= 0) candles.value[idx] = c
        } else {
          // 新蜡烛，追加
          candles.value.push(c)
          timeMap.set(c.time, true)
        }
      }
      return data
    } catch { return [] }
  }

  /** 加载更多历史数据（before 时间戳之前），滚动到左边缘时调用 */
  async function fetchMoreCandles(timeframe: string, before: number, count = 500) {
    if (before <= 0 || before === lastMoreBefore) return []
    lastMoreBefore = before
    try {
      const resp = await fetch(`/api/market/candles?timeframe=${timeframe}&count=${count}&before=${before}`)
      const data: Candle[] = await resp.json()
      if (data && data.length > 0) {
        const existTimes = new Set(candles.value.map(c => c.time))
        const newCandles = data.filter(c => !existTimes.has(c.time))
        candles.value = [...newCandles, ...candles.value]
        // 不设上限：保留全部已加载历史，滚动回看不用重新加载。
        // 当前单周期最多几万根（M5 约1.6万），内存完全可承受
      }
      return data
    } catch { return [] }
  }

  return { bid, ask, spread, candles, midPrice, loading, updateTick, fetchPrice, fetchCandles, fetchLatestCandles, fetchMoreCandles }
})
