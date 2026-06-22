/**
 * 监控告警 Store — 前端巡检引擎状态
 *
 * 用户点击"清除告警"后，当前告警被标记为已读（dismissedKeys），
 * 巡检时同 key 的告警不再出现。数据库不删除，仅前端隐藏已读项。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getEngineStatus } from '@/api/client'
import { usePriceStore } from './prices'
import { usePositionStore } from './positions'
import type { PatrolAlert } from '@/types'

const ALERT_SL = 4480.03
const SHARP_MOVE_THRESHOLD = 50    // 短期剧烈波动阈值（点）
const MOVE_WINDOW_SECONDS = 60     // 检测窗口（秒）
const PRICE_SAMPLE_INTERVAL = 10   // 采样间隔（秒）
const DISMISSED_STORAGE_KEY = 'patrol_dismissed_keys'

function loadDismissed(): Set<string> {
  try {
    const raw = localStorage.getItem(DISMISSED_STORAGE_KEY)
    if (raw) return new Set(JSON.parse(raw))
  } catch { /* ignore */ }
  return new Set()
}

function saveDismissed(keys: Set<string>) {
  try {
    localStorage.setItem(DISMISSED_STORAGE_KEY, JSON.stringify([...keys]))
  } catch { /* ignore */ }
}

export const usePatrolStore = defineStore('patrol', () => {
  const alerts = ref<PatrolAlert[]>([])
  const lastCheckTime = ref<string>('')
  const dismissedKeys = ref<Set<string>>(loadDismissed())
  let alertId = 0
  let timer: ReturnType<typeof setInterval> | null = null
  let lastSampleTime = 0
  let priceHistory: { price: number; time: number }[] = []

  // 状态跟踪（变化检测用）
  const prevState = ref({
    engineRunning: false as boolean | null,
    bridgeConnected: false as boolean | null,
    positionTickets: new Set<number>(),
    reportedSl4480: false,
  })

  // 已报告过的错误日志时间戳（避免重复报告历史错误）
  let lastSeenErrorTime = ''

  // === 计算属性 ===
  const health = computed<'normal' | 'warning' | 'critical'>(() => {
    if (alerts.value.some(a => a.level === 'critical')) return 'critical'
    if (alerts.value.some(a => a.level === 'warning')) return 'warning'
    return 'normal'
  })

  const criticalCount = computed(() => alerts.value.filter(a => a.level === 'critical').length)
  const warningCount = computed(() => alerts.value.filter(a => a.level === 'warning').length)
  const unreadCount = computed(() => alerts.value.length)

  // === 内部方法 ===
  function addAlert(level: PatrolAlert['level'], message: string, key?: string) {
    // 已被用户清除（已读），不再报告
    if (key && dismissedKeys.value.has(key)) return
    // 无 key 时用 message，检查是否已有相同 dedupKey 的告警
    const dedupKey = key || message
    if (alerts.value.some(a => (a.key || a.message) === dedupKey)) return

    alerts.value.unshift({
      id: ++alertId,
      time: new Date().toLocaleTimeString(),
      level,
      message,
      key: dedupKey,
    })
    if (alerts.value.length > 200) {
      alerts.value = alerts.value.slice(0, 200)
    }
  }

  // === 巡检逻辑 ===
  async function runPatrol(): Promise<void> {
    const now = new Date().toLocaleString()
    lastCheckTime.value = now
    const priceStore = usePriceStore()
    const posStore = usePositionStore()

    // ---- 1. 引擎状态 ----
    try {
      const status = await getEngineStatus()
      const running = status.status === 'running'
      const bridge = status.bridge_connected ?? false
      const uptime = status.uptime_seconds ?? 0

      if (prevState.value.engineRunning === null) {
        // 首次运行，只记录不报
      } else if (!running) {
        addAlert('critical',
          `引擎已停止！${prevState.value.engineRunning === true ? '(刚刚停止)' : ''}`,
          'engine_stopped')
      } else if (!bridge) {
        addAlert('critical', 'Bridge 桥接已断开！', 'bridge_disconnected')
      } else if (prevState.value.engineRunning === false) {
        addAlert('info',
          `引擎恢复运行（已运行 ${Math.floor(uptime / 60)} 分钟）`,
          'engine_recovered')
      }

      prevState.value.engineRunning = running
      prevState.value.bridgeConnected = bridge
    } catch {
      addAlert('critical', '无法连接引擎 API！后端可能未启动', 'api_unreachable')
    }

    // ---- 2. 短期剧烈波动检测 ----
    const bid = priceStore.bid
    if (bid > 0) {
      const now = Date.now()
      // 按采样间隔记录价格
      if (now - lastSampleTime >= PRICE_SAMPLE_INTERVAL * 1000) {
        priceHistory.push({ price: bid, time: now })
        lastSampleTime = now
        // 清理超出窗口的历史样本
        const cutoff = now - MOVE_WINDOW_SECONDS * 1000
        priceHistory = priceHistory.filter(s => s.time >= cutoff)
        // 最多保留 30 个样本防内存泄漏
        if (priceHistory.length > 30) priceHistory = priceHistory.slice(-30)
      }
      // 在窗口内查找最大波动
      if (priceHistory.length >= 2) {
        const oldest = priceHistory[0]
        const maxMove = Math.abs(bid - oldest.price)
        if (maxMove >= SHARP_MOVE_THRESHOLD) {
          const direction = bid > oldest.price ? '急涨' : '急跌'
          addAlert('warning',
            `价格剧烈波动：${direction} ${maxMove.toFixed(1)} 点（${oldest.price} → ${bid}，${MOVE_WINDOW_SECONDS}s 内）`,
            'sharp_move')
          // 触发后清空历史，避免短时间内重复报警
          priceHistory = []
        }
      }
    }

    // ---- 3. 持仓变化 ----
    const currentTickets = new Set(posStore.items.map(p => p.ticket))
    const prevTickets = prevState.value.positionTickets

    if (prevTickets.size > 0 && currentTickets.size !== prevTickets.size) {
      const closedTickets = new Set([...prevTickets].filter(t => !currentTickets.has(t)))

      // 检测 SL=4480.03 平仓
      if (closedTickets.size > 0 && !prevState.value.reportedSl4480) {
        const closedPos = posStore.items.filter(p => closedTickets.has(p.ticket))
        for (const p of closedPos) {
          if (Math.abs(p.stop_loss - ALERT_SL) < 0.01) {
            addAlert('critical',
              `止损触发！单 ${p.ticket} SL=${ALERT_SL} 被触发平仓`,
              `sl_triggered_${p.ticket}`)
            prevState.value.reportedSl4480 = true
          }
        }
      }

      // 新开仓
      const newTickets = [...currentTickets].filter(t => !prevTickets.has(t))
      for (const t of newTickets) {
        const p = posStore.items.find(x => x.ticket === t)
        if (p) {
          addAlert('info',
            `新开仓 #${p.ticket} ${p.order_type} ${p.volume} lot @ ${p.open_price}`,
            `position_new_${p.ticket}`)
        }
      }

      // 平仓
      for (const t of closedTickets) {
        addAlert('info', `平仓 #${t}`, `position_close_${t}`)
      }
    }

    prevState.value.positionTickets = currentTickets

    // ---- 4. 错误日志（仅新出现的错误，跳过历史 ----
    try {
      const { getLogs } = await import('@/api/client')
      const logs = await getLogs('ERROR', 20)
      if (logs && logs.length > 0) {
        // 找出最新的错误日志时间戳
        let latestTime = ''
        for (const l of logs) {
          const ts = (l as any).time || ''
          if (ts > latestTime) latestTime = ts
        }
        // 只有出现了比上次更新的错误才报警
        if (latestTime > lastSeenErrorTime) {
          for (const l of logs) {
            const ts = (l as any).time || ''
            if (ts <= lastSeenErrorTime) continue // 跳过已见过的
            const logKey = `log_${(l as any).id || ts}`
            addAlert('warning',
              `日志错误: ${l.message.substring(0, 120)}`,
              logKey)
          }
          lastSeenErrorTime = latestTime
        }
      }
    } catch {
      // ignore log fetch errors
    }

    return
  }

  // === 生命周期 ===
  function start(intervalMs = 30000) {
    stop()
    runPatrol()
    timer = setInterval(() => runPatrol(), intervalMs)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function clearAlerts() {
    for (const a of alerts.value) {
      if (a.key) dismissedKeys.value.add(a.key)
    }
    saveDismissed(dismissedKeys.value)
    alerts.value = []
    prevState.value.reportedSl4480 = false
    priceHistory = []
  }

  return {
    alerts, health, lastCheckTime,
    criticalCount, warningCount, unreadCount,
    runPatrol, start, stop, clearAlerts, prevState,
  }
})
