/**
 * chartSync.ts 单元测试 — 验证图表联动工具函数
 */
import { describe, it, expect } from 'vitest'
import {
  indexSeriesValues,
  getPaneSeriesList,
  type ChartRef,
  type SyncLock,
} from '../src/utils/chartSync'

// 模拟 series 数据
const mockSeries = {
  data: () => [
    { time: 100, value: 50 },
    { time: 200, value: 55 },
    { time: 300, value: 45 },
  ],
}

const mockCandleSeries = {
  data: () => [
    { time: 100, close: 4300 },
    { time: 200, close: 4310 },
    { time: 300, close: 4320 },
  ],
}

describe('indexSeriesValues', () => {
  it('构建 time → value 映射', () => {
    const map = indexSeriesValues(mockSeries)
    expect(map.size).toBe(3)
    expect(map.get(100)).toBe(50)
    expect(map.get(200)).toBe(55)
    expect(map.get(300)).toBe(45)
  })

  it('空 series 返回空 Map', () => {
    const emptySeries = { data: () => [] }
    const map = indexSeriesValues(emptySeries)
    expect(map.size).toBe(0)
  })

  it('data() 抛异常时返回空 Map', () => {
    const badSeries = { data: () => { throw new Error('test') } }
    const map = indexSeriesValues(badSeries)
    expect(map.size).toBe(0)
  })
})

describe('getPaneSeriesList', () => {
  it('line + price 结构', () => {
    const paneSeries = {
      bbi: { line: 'series_a', price: 'series_b' },
    }
    const result = getPaneSeriesList('bbi', paneSeries)
    expect(result).toEqual(['series_a', 'series_b'])
  })

  it('k + d 结构', () => {
    const paneSeries = {
      stoch: { k: 'series_k', d: 'series_d' },
    }
    const result = getPaneSeriesList('stoch', paneSeries)
    expect(result).toEqual(['series_k', 'series_d'])
  })

  it('macd + signal 结构', () => {
    const paneSeries = {
      macd: { macd: 'series_macd', signal: 'series_signal' },
    }
    const result = getPaneSeriesList('macd', paneSeries)
    expect(result).toEqual(['series_macd', 'series_signal'])
  })

  it('单个 series', () => {
    const paneSeries = {
      atr: 'series_atr',
    }
    const result = getPaneSeriesList('atr', paneSeries)
    expect(result).toEqual(['series_atr'])
  })

  it('不存在的 pane 返回空数组', () => {
    const paneSeries = {}
    const result = getPaneSeriesList('nonexistent', paneSeries)
    expect(result).toEqual([])
  })
})
