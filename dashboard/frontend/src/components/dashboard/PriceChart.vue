<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { usePriceStore } from '@/stores/prices'
import { createChart, ColorType } from 'lightweight-charts'

const store = usePriceStore()
const chartContainer = ref<HTMLDivElement>()
let chart: ReturnType<typeof createChart> | null = null
let candleSeries: any = null

const timeframes = ['M5', 'M15', 'H1', 'H4', 'D1']
const activeTf = ref('H1')

onMounted(() => {
  if (!chartContainer.value) return
  chart = createChart(chartContainer.value, {
    layout: {
      background: { type: ColorType.Solid, color: '#1a1d23' },
      textColor: '#8b8f97',
    },
    grid: {
      vertLines: { color: '#2d3139' },
      horzLines: { color: '#2d3139' },
    },
    width: chartContainer.value.clientWidth,
    height: 400,
    timeScale: { timeVisible: false, borderColor: '#2d3139' },
    rightPriceScale: { borderColor: '#2d3139' },
    crosshair: { mode: 0 },
  })

  candleSeries = chart.addCandlestickSeries({
    upColor: '#0ecb81',
    downColor: '#f6465d',
    borderUpColor: '#0ecb81',
    borderDownColor: '#f6465d',
    wickUpColor: '#0ecb81',
    wickDownColor: '#f6465d',
  })

  loadCandles()

  const observer = new ResizeObserver(() => {
    if (chart && chartContainer.value) {
      chart.applyOptions({ width: chartContainer.value.clientWidth })
    }
  })
  observer.observe(chartContainer.value)
})

onUnmounted(() => chart?.remove())

async function loadCandles() {
  await store.fetchCandles(activeTf.value, 200)
  if (candleSeries && store.candles.length > 0) {
    candleSeries.setData(
      store.candles.map(c => ({
        time: c.time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
    )
  }
}

function switchTf(tf: string) {
  activeTf.value = tf
  loadCandles()
}
</script>

<template>
  <n-card title="XAUUSD 价格图表" size="small">
    <template #header-extra>
      <n-space size="small">
        <n-button v-for="tf in timeframes" :key="tf" size="tiny"
                  :type="activeTf === tf ? 'primary' : 'default'"
                  @click="switchTf(tf)">
          {{ tf }}
        </n-button>
      </n-space>
    </template>

    <!-- 实时价格栏 -->
    <n-grid :cols="4" :x-gap="16" style="margin-bottom: 8px;">
      <n-gi><n-text depth="3">买价</n-text> <span class="price-up"><strong>{{ store.bid.toFixed(2) }}</strong></span></n-gi>
      <n-gi><n-text depth="3">卖价</n-text> <span class="price-down"><strong>{{ store.ask.toFixed(2) }}</strong></span></n-gi>
      <n-gi><n-text depth="3">点差</n-text> <strong>{{ store.spread.toFixed(2) }}</strong></n-gi>
      <n-gi><n-text depth="3">中间价</n-text> <span class="price-gold"><strong>{{ store.midPrice.toFixed(2) }}</strong></span></n-gi>
    </n-grid>

    <!-- 加载态 -->
    <div v-if="store.loading" style="height: 400px; display: flex; align-items: center; justify-content: center;">
      <n-spin size="large" />
    </div>

    <!-- 空态 -->
    <div v-else-if="store.candles.length === 0" style="height: 400px; display: flex; align-items: center; justify-content: center;">
      <n-result status="info" title="暂无数据" description="连接 MT4 后自动加载 K 线数据" size="small" />
    </div>

    <!-- 图表 -->
    <div v-else ref="chartContainer" style="width: 100%; height: 400px;"></div>
  </n-card>
</template>
