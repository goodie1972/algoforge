// 统一时间格式化工具 — 基于 date-fns (ESM)
//
// 所有输出统一为 UTC+8（北京时间）字面时间，与运行环境时区无关（Windows/服务器均一致）。
// 兼容性：
//   - Unix 秒 / 毫秒时间戳（number）
//   - Unix 秒 / 毫秒时间戳的数字字符串（"1700000000" / "1700000000000"）
//   - 后端返回的日期字符串："YYYY-MM-DD HH:mm:ss"、"YYYY-MM-DD HH:mm"、"YYYY-MM-DD"（视为 UTC+8 字面值）
//   - 其它可被 Date 解析的 ISO 字符串（按绝对时刻换算为 UTC+8）
// 空值 / 无法识别的输入一律返回 '-'
import { format, isValid, parse } from 'date-fns'

// ========== 时间格式常量 ==========
/** yyyy-MM-dd HH:mm:ss */
export const FMT_DATETIME = 'yyyy-MM-dd HH:mm:ss'
/** yyyy-MM-dd */
export const FMT_DATE = 'yyyy-MM-dd'
/** HH:mm */
export const FMT_HM = 'HH:mm'

const MS_PER_SEC = 1000
const UTC8_OFFSET_MS = 8 * 60 * 60 * 1000
/** 数值 >= 1e12 视为 Unix 毫秒时间戳，否则视为 Unix 秒 */
const MS_THRESHOLD = 1e12

/**
 * 本机时区相对 UTC 的偏移（毫秒）：getTimezoneOffset() 返回「UTC - 本地」的分钟数，
 * 如 UTC+8 环境为 -480（本地快 8 小时）。
 */
const LOCAL_OFFSET_MS = new Date().getTimezoneOffset() * 60 * 1000

/**
 * date-fns 的 format() 只能输出 Date 的本地字段。给定一个「字面字段」Date（其各自
 * UTC 字段拼起来即目标显示值），平移 +LOCAL_OFFSET_MS 后，format() 输出的本地字段
 * 恰好等于该字面值 —— 无论运行环境处于哪个时区，结果都固定一致。
 */
function asLocalFields(u: Date): Date {
  return new Date(u.getTime() + LOCAL_OFFSET_MS)
}

function safeFormat(d: Date, fmt: string): string {
  return isValid(d) ? format(d, fmt) : '-'
}

/** Unix 秒时间戳 → UTC+8 字面显示 */
function formatFromSeconds(ts: number, fmt: string): string {
  const utc8 = new Date(ts * MS_PER_SEC + UTC8_OFFSET_MS)
  return safeFormat(asLocalFields(utc8), fmt)
}

/** Unix 毫秒时间戳 → UTC+8 字面显示 */
function formatFromMs(ts: number, fmt: string): string {
  const utc8 = new Date(ts + UTC8_OFFSET_MS)
  return safeFormat(asLocalFields(utc8), fmt)
}

/**
 * 按数字判断是 Unix 秒还是毫秒，并格式化为 UTC+8。
 * 输入必须是有限数字（NaN / Infinity 返回 '-'）。
 */
function formatFromNumber(n: number, fmt: string): string {
  if (!Number.isFinite(n)) return '-'
  return Math.abs(n) >= MS_THRESHOLD ? formatFromMs(n, fmt) : formatFromSeconds(n, fmt)
}

/** 日期字符串解析候选格式（均为无时区的 UTC+8 字面值格式） */
const STRING_PATTERNS = [FMT_DATETIME, 'yyyy-MM-dd HH:mm', FMT_DATE]

/**
 * Unix 秒时间戳 → UTC+8 字符串。
 * @param ts  Unix 秒时间戳
 * @param format 输出格式，默认 FMT_DATETIME
 */
export function formatTimestamp(ts: number, format: string = FMT_DATETIME): string {
  return formatFromNumber(ts, format)
}

/**
 * Unix 毫秒时间戳 → UTC+8 字符串。
 * @param ts  Unix 毫秒时间戳
 * @param format 输出格式，默认 FMT_DATETIME
 */
export function formatTimestampMs(ts: number, format: string = FMT_DATETIME): string {
  return formatFromNumber(ts, format)
}

/**
 * 兼容后端返回的字符串：可能是 "YYYY-MM-DD HH:mm:ss"（UTC+8 字面值）或 Unix 数字串（秒 / 毫秒）。
 * 自动识别并格式化为 UTC+8；无法识别返回 '-'。
 * @param str  后端返回的字符串（宽松类型，数字 / 空值同样处理）
 * @param format 输出格式，默认 FMT_DATETIME
 */
export function formatDateTime(
  str: string | number | null | undefined,
  format: string = FMT_DATETIME,
): string {
  if (str === null || str === undefined) return '-'
  const s = String(str).trim()
  if (s === '') return '-'

  // 纯数字（含负数）→ Unix 时间戳
  if (/^-?\d+$/.test(s)) {
    // 超长数字串可能超出安全整数范围（Number 会变 Infinity / 丢精度）
    const n = Number(s)
    return Number.isSafeInteger(n) ? formatFromNumber(n, format) : '-'
  }

  // 无时区日期字符串 → 按 UTC+8 字面值原样输出
  for (const p of STRING_PATTERNS) {
    const d = parse(s, p, new Date())
    if (isValid(d)) return safeFormat(d, format)
  }

  // 兜底：ISO / 其它 Date 可解析的字符串 → 按绝对时刻换算 UTC+8
  const t = new Date(s).getTime()
  if (!Number.isNaN(t)) return formatFromMs(t, format)

  return '-'
}

/**
 * 通用时间格式化入口：自动判断输入类型并返回 UTC+8 格式化结果。
 * 支持 Unix 秒 / 毫秒（number 或数字字符串）、日期字符串；空值（null / undefined / ''）返回 '-'。
 * @param value  待格式化的值
 * @param format 输出格式，默认 FMT_DATETIME
 */
export function smartTs(value: number | string | null | undefined, format: string = FMT_DATETIME): string {
  if (value === null || value === undefined || value === '') return '-'
  return formatDateTime(value, format)
}

/**
 * 从表格行数据取时间并格式化：
 * 优先使用后端新增的 *_ts 字段（Unix 秒 / 毫秒），
 * 缺省（或无法解析）时回退旧字段（数字时间戳 / 日期字符串），
 * 两者都为空返回 '-'。用于 /api/trades/history、/api/positions 等行数据。
 * @param row       行数据对象
 * @param tsKey     _ts 字段名，如 'open_time_ts'
 * @param legacyKey 旧字段名，如 'open_time'
 * @param format    输出格式，默认 FMT_DATETIME
 */
export function fmtRowTime(
  row: Record<string, any>,
  tsKey: string,
  legacyKey: string,
  format: string = FMT_DATETIME,
): string {
  // 优先：新增的 _ts 字段
  const ts = row[tsKey]
  if (ts !== null && ts !== undefined && ts !== '') {
    const v = smartTs(ts, format)
    if (v !== '-') return v
  }
  // 回退：旧字段（无法识别时保持旧行为——原样显示）
  const legacy = row[legacyKey]
  if (legacy === null || legacy === undefined || legacy === '') return '-'
  const v = smartTs(legacy, format)
  return v !== '-' ? v : String(legacy)
}