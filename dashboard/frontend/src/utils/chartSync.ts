/**
 * chartSync.ts — 图表联动工具函数（纯函数，无 Vue 依赖）
 *
 * 从 TradingTerminal.vue 抽离，负责：
 * - 双向时间轴同步（缩放/拖拽联动）
 * - 十字光标跨图联动（主图 ↔ 9 个副图）
 * - 时间标签 DOM 更新
 */

// 同步锁对象 — 通过引用传递，修改 value 属性控制重入
export interface SyncLock { value: boolean }

export interface ChartRef {
  chart: any
  candleSeries: any
  paneCharts: Record<string, any>
  paneSeries: Record<string, any>
  chartContainer: HTMLDivElement | undefined
  lock: SyncLock
}

/**
 * 双向时间轴同步：任意图缩放时所有图一同缩放
 */
export function syncAllChartsFrom(source: any, ref: ChartRef) {
  if (ref.lock.value) return
  ref.lock.value = true
  try {
    const range = source.timeScale().getVisibleLogicalRange()
    if (range) {
      if (source !== ref.chart) {
        ref.chart?.timeScale().setVisibleLogicalRange(range)
      }
      for (const pc of Object.values(ref.paneCharts)) {
        if (pc !== source) pc.timeScale().setVisibleLogicalRange(range)
      }
    }
  } finally {
    ref.lock.value = false
  }
}

/**
 * 构建 series 的 time → value 索引（供跨图同步取真实指标值）
 */
export function indexSeriesValues(series: any): Map<number, number> {
  const m = new Map<number, number>()
  try {
    const raw = (series as any).data() as any[]
    if (Array.isArray(raw)) {
      for (const pt of raw) {
        if (pt?.time == null) continue
        const t = Number(pt.time)
        let v = pt.close ?? pt.value ?? pt.macd ?? pt.histogram ?? pt.k ?? pt.d ?? pt.pdi ?? pt.ndi
        if (v == null && pt.value != null) v = pt.value
        if (v != null) m.set(t, Number(v))
      }
    }
  } catch { /* ignore */ }
  return m
}

/**
 * 返回指定 pane 的 series 数组（处理不同结构）
 */
export function getPaneSeriesList(name: string, paneSeries: Record<string, any>): any[] {
  const ps = paneSeries[name]
  if (!ps) return []
  if (Array.isArray(ps)) return ps
  // line + price (BB width ratio 等)
  if (ps.line && ps.price) return [ps.line, ps.price]
  // stoch: k + d (+ ob + os)
  if (ps.k && ps.d) return [ps.k, ps.d, ps.ob, ps.os].filter(Boolean)
  // macd: macd + signal + histogram
  if (ps.macd && ps.signal) return [ps.macd, ps.signal, ps.histogram].filter(Boolean)
  // rsi: series + overbought + oversold
  if (ps.series && ps.overbought) return [ps.series, ps.overbought, ps.oversold].filter(Boolean)
  // mfi: series + ob/os/mid 参考线
  if (ps.series && ps.ob) return [ps.series, ps.ob, ps.os, ps.mid].filter(Boolean)
  // di: pdi + ndi + 参考线
  if (ps.pdi && ps.ndi) return [ps.pdi, ps.ndi, ps.di_ref20, ps.di_ref30].filter(Boolean)
  // 单 series (atr 等)
  if (ps.line) return [ps.line]
  if (ps.k) return [ps.k]
  // volume/adx 等直接是 series 对象
  if (typeof ps === 'object' && typeof ps.setData === 'function') return [ps]
  return [ps]
}

/**
 * 十字光标跨图联动：同步所有图竖线 + 传入真实指标值
 */
export function syncCrosshairToAll(tc: any, t: number, ref: ChartRef) {
  if (ref.lock.value) return
  ref.lock.value = true
  try {
    const targets: Array<{ chart: any; series: any[]; height: number }> = []
    if (ref.chart && ref.chart !== tc) {
      // 获取主图高度
      const height = getChartHeight(ref.chart)
      targets.push({ chart: ref.chart, series: [ref.candleSeries], height })
    }
    for (const name of Object.keys(ref.paneCharts)) {
      const pc = ref.paneCharts[name]
      if (pc && pc !== tc) {
        // 获取副图高度
        const height = getChartHeight(pc)
        targets.push({ chart: pc, series: getPaneSeriesList(name, ref.paneSeries), height })
      }
    }
    
    // 获取源图表的高度
    const sourceHeight = getChartHeight(tc)
    
    for (const { chart: c2, series, height: targetHeight } of targets) {
      if (!c2 || series.length === 0) continue
      let price = 0
      for (const s of series) {
        const map = indexSeriesValues(s)
        if (map.has(t)) { price = map.get(t)!; break }
        let nearest: number | null = null
        const entries = Array.from(map.entries());
        for (const [tt, vv] of entries) {
          if (tt <= t) nearest = vv
          else break
        }
        if (nearest != null) { price = nearest; break }
      }
      
      // 使用 setCrosshairPosition 的完整签名，分别处理 X 和 Y 坐标
      // X 坐标直接使用时间，Y 坐标需要根据图表高度进行转换
      try {
        // 对于 Y 坐标，如果当前图表高度与源图表高度不同，则进行坐标转换
        if (sourceHeight !== targetHeight) {
          // 尝试获取源图表的 Y 坐标
          const sourceY = getCrosshairYCoordinate(tc, price)
          if (sourceY !== null) {
            // 将源图表的 Y 坐标转换为相对位置，然后映射到目标图表高度
            const relativeY = sourceY / sourceHeight
            const targetY = relativeY * targetHeight
            c2.setCrosshairPosition(targetY, t as any, series[0])
          } else {
            // 如果无法获取源 Y 坐标，则直接使用价格值
            c2.setCrosshairPosition(price, t as any, series[0])
          }
        } else {
          c2.setCrosshairPosition(price, t as any, series[0])
        }
      } catch { /* ignore */ }
    }
  } finally {
    ref.lock.value = false
  }
}

/**
 * 获取图表的高度
 */
function getChartHeight(chart: any): number {
  try {
    // 尝试通过不同的方式获取图表高度
    if (chart._internal_charts && chart._internal_charts[0] && typeof chart._internal_charts[0].height === 'function') {
      return chart._internal_charts[0].height()
    }
    // 如果上述方法不可用，尝试其他可能的访问方式
    if (chart.height && typeof chart.height === 'function') {
      return chart.height()
    }
    // 默认返回主图高度
    return 420 // 默认主图高度
  } catch {
    return 420 // 默认主图高度
  }
}

/**
 * 获取十字光标在源图表上的 Y 坐标
 */
function getCrosshairYCoordinate(chart: any, price: number): number | null {
  try {
    // Lightweight-Charts 提供了将价格转换为 Y 坐标的函数
    if (chart.priceScale && typeof chart.priceScale === 'function') {
      const priceScale = chart.priceScale('right') || chart.priceScale('left')
      if (priceScale && typeof priceScale.priceToCoordinate === 'function') {
        return priceScale.priceToCoordinate(price)
      }
    }
    // 如果上述方法不可用，尝试其他可能的方式
    if (chart.priceToCoordinate && typeof chart.priceToCoordinate === 'function') {
      return chart.priceToCoordinate(price)
    }
    return null
  } catch {
    return null
  }
}

/**
 * 清除所有图的十字光标
 */
export function clearCrosshairAll(tc: any, ref: ChartRef) {
  if (ref.lock.value) return
  if (ref.chart && ref.chart !== tc) { try { ref.chart.clearCrosshairPosition() } catch {} }
  for (const name of Object.keys(ref.paneCharts)) {
    const pc = ref.paneCharts[name]
    if (pc && pc !== tc) { try { pc.clearCrosshairPosition() } catch {} }
  }
  const el = document.getElementById('tc-crosshair-time')
  if (el) el.remove()
}

/**
 * 更新十字光标时间标签（DOM 元素）
 */
export function updateCrosshairTimeLabel(t: number, container: HTMLDivElement | undefined) {
  if (!container) return
  let el = document.getElementById('tc-crosshair-time') as HTMLDivElement | null
  if (!el) {
    el = document.createElement('div')
    el.id = 'tc-crosshair-time'
    el.style.cssText = 'position:absolute;top:2px;right:30px;z-index:20;font-size:12px;font-weight:600;padding:2px 8px;border-radius:4px;pointer-events:none;'
    container.appendChild(el)
  }
  const isDark = document.documentElement.classList.contains('dark')
  el.style.color = isDark ? '#e5e7eb' : '#1f2937'
  el.style.background = isDark ? 'rgba(31,41,55,0.85)' : 'rgba(255,255,255,0.9)'
  el.style.border = isDark ? '1px solid #4b5563' : '1px solid #d1d5db'
  const d = new Date(t * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  el.textContent = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes())
}

/**
 * 十字光标移动事件处理（入口）
 */
export function onCrosshairMove(tc: any, param: any, ref: ChartRef) {
  const t = param?.time
  if (t != null) {
    syncCrosshairToAll(tc, Number(t), ref)
    updateCrosshairTimeLabel(Number(t), ref.chartContainer)
  } else if (param && !param.point) {
    clearCrosshairAll(tc, ref)
  }
}
