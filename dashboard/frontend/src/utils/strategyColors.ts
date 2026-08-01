/**
 * 策略颜色分配器
 * ==============
 * - 每个策略名通过哈希得到一个固定的色相（0-360）
 * - 带 _optimized / _original 后缀的变体，从基名色相派生（同色系不同深浅）
 * - 最多 256 色，策略删除前颜色不变
 */

// HSL → hex 转换
function hslToHex(h: number, s: number, l: number): string {
  s /= 100
  l /= 100
  const a = s * Math.min(l, 1 - l)
  const f = (n: number) => {
    const k = (n + h / 30) % 12
    const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1)
    return Math.round(255 * color)
      .toString(16)
      .padStart(2, '0')
  }
  return `#${f(0)}${f(8)}${f(4)}`
}

// 简易哈希：str → 0-255 整数
function hashName(name: string): number {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    const char = name.charCodeAt(i)
    hash = ((hash << 5) - hash + char) | 0
  }
  return Math.abs(hash) & 0xff // 0-255
}

/** 判断是否是变体后缀 */
function isVariant(name: string): string | null {
  const m = name.match(/^(.*?)_(optimized|original)$/)
  return m ? m[1] : null
}

/**
 * 获取策略颜色
 * @param name 策略名
 * @returns 十六进制颜色字符串
 */
export function getStrategyColor(name: string): string {
  const base = isVariant(name)

  if (base) {
    // 变体策略：用基名定色相，变体加深/变浅
    const baseHue = (hashName(base) / 255) * 360
    // optimized → 深色, original → 浅色
    if (name.endsWith('_optimized')) {
      return hslToHex(baseHue, 70, 30) // 深色
    } else {
      return hslToHex(baseHue, 60, 55) // 浅色
    }
  } else {
    // 主策略：标准色
    const hue = (hashName(name) / 255) * 360
    return hslToHex(hue, 65, 50)
  }
}

/**
 * 根据背景色亮度自动选择文字色（白底黑字 / 黑底白字）
 * @param hex 六进制颜色字符串
 * @returns '#000' 或 '#fff'
 */
export function textColorForBg(hex: string): string {
  // 解析 hex 为 RGB
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  // 相对亮度公式 (W3C WCAG)
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
  return luminance > 0.5 ? '#000' : '#fff'
}

/**
 * 获取策略标签文字颜色（自动根据背景色亮度选择）
 * @param name 策略名
 * @returns '#000' 或 '#fff'
 */
export function getStrategyTextColor(name: string): string {
  return textColorForBg(getStrategyColor(name))
}

/**
 * 预生成的策略颜色映射表（兼容旧代码的 Record 方式）
 */
export function buildStrategyColors(strategies: string[]): Record<string, string> {
  const map: Record<string, string> = {}
  for (const name of strategies) {
    map[name] = getStrategyColor(name)
  }
  return map
}
