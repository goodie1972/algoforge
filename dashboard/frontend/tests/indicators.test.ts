/**
 * indicators.ts 单元测试 — 验证所有指标计算函数
 */
import { describe, it, expect } from 'vitest'
import {
  calcEMA, calcSMA, calcBollinger, calcRSI, calcStoch,
  calcMACD, calcATR, calcVolume, calcADX, calcMFI,
  type CandleData,
} from '../src/utils/indicators'

// 生成测试用 K 线数据（50根，价格从 4300 递增到 4350）
function makeCandles(n: number = 50): CandleData[] {
  const candles: CandleData[] = []
  let price = 4300
  for (let i = 0; i < n; i++) {
    const open = price
    const close = price + 1
    const high = close + 2
    const low = open - 2
    candles.push({ time: 1700000000 + i * 3600, open, high, low, close, volume: 100 + i })
    price = close
  }
  return candles
}

describe('calcEMA', () => {
  it('返回正确数量的数据点', () => {
    const candles = makeCandles(50)
    const ema = calcEMA(candles, 14)
    expect(ema.length).toBeGreaterThan(0)
    expect(ema.length).toBeLessThanOrEqual(candles.length)
  })

  it('每个点有 time 和 value', () => {
    const candles = makeCandles(30)
    const ema = calcEMA(candles, 10)
    ema.forEach(p => {
      expect(p).toHaveProperty('time')
      expect(p).toHaveProperty('value')
      expect(p.value).not.toBeNaN()
    })
  })
})

describe('calcSMA', () => {
  it('SMA 值在合理范围内', () => {
    const candles = makeCandles(50)
    const sma = calcSMA(candles, 14)
    expect(sma.length).toBeGreaterThan(0)
    const lastVal = sma[sma.length - 1].value
    // SMA 应在最低价和最高价之间
    expect(lastVal).toBeGreaterThan(4290)
    expect(lastVal).toBeLessThan(4360)
  })
})

describe('calcBollinger', () => {
  it('返回 upper/middle/lower 三条线', () => {
    const candles = makeCandles(50)
    const bb = calcBollinger(candles, 20, 2)
    expect(bb.length).toBeGreaterThan(0)
    bb.forEach(p => {
      expect(p).toHaveProperty('upper')
      expect(p).toHaveProperty('middle')
      expect(p).toHaveProperty('lower')
      expect(p.upper).toBeGreaterThanOrEqual(p.middle)
      expect(p.middle).toBeGreaterThanOrEqual(p.lower)
    })
  })
})

describe('calcRSI', () => {
  it('RSI 值在 0-100 之间', () => {
    const candles = makeCandles(50)
    const rsi = calcRSI(candles, 14)
    expect(rsi.length).toBeGreaterThan(0)
    rsi.forEach(p => {
      expect(p.value).toBeGreaterThanOrEqual(0)
      expect(p.value).toBeLessThanOrEqual(100)
    })
  })
})

describe('calcStoch', () => {
  it('返回 k 和 d 两条线', () => {
    const candles = makeCandles(50)
    const stoch = calcStoch(candles, 14, 3, 3)
    expect(stoch).toHaveProperty('k')
    expect(stoch).toHaveProperty('d')
    expect(stoch.k.length).toBeGreaterThan(0)
    expect(stoch.d.length).toBeGreaterThan(0)
  })
})

describe('calcMACD', () => {
  it('返回 macd/signal/histogram', () => {
    const candles = makeCandles(50)
    const macd = calcMACD(candles, 12, 26, 9)
    expect(macd).toHaveProperty('macd')
    expect(macd).toHaveProperty('signal')
    expect(macd).toHaveProperty('histogram')
  })
})

describe('calcATR', () => {
  it('ATR 值为正数', () => {
    const candles = makeCandles(50)
    const atr = calcATR(candles, 14)
    expect(atr.length).toBeGreaterThan(0)
    atr.forEach(p => {
      expect(p.value).toBeGreaterThan(0)
    })
  })
})

describe('calcVolume', () => {
  it('返回成交量数据', () => {
    const candles = makeCandles(50)
    const vol = calcVolume(candles)
    expect(vol.length).toBeGreaterThan(0)
    vol.forEach(p => {
      expect(p).toHaveProperty('time')
      expect(p).toHaveProperty('value')
    })
  })
})

describe('calcADX', () => {
  it('返回 adx/pdi/ndi', () => {
    const candles = makeCandles(50)
    const result = calcADX(candles, 14)
    expect(result).toHaveProperty('adx')
    expect(result).toHaveProperty('pdi')
    expect(result).toHaveProperty('ndi')
  })
})

describe('calcMFI', () => {
  it('MFI 值在 0-100 之间', () => {
    const candles = makeCandles(50)
    const mfi = calcMFI(candles, 14)
    expect(mfi.length).toBeGreaterThan(0)
    mfi.forEach(p => {
      if (!isNaN(p.value)) {
        expect(p.value).toBeGreaterThanOrEqual(0)
        expect(p.value).toBeLessThanOrEqual(100)
      }
    })
  })
})
