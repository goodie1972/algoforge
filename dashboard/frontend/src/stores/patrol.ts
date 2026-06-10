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

const REFERENCE_PRICE = 4507.0
const PRICE_DEVIATION = 20.0
const ALERT_SL = 4480.03
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

  // 状态跟踪（变化检测用）
  const prevState = ref({
    engineRunning: false as boolean | null,
    bridgeConnected: false as boolean | null,
    positionTickets: new Set<number>(),
    reportedDeviation: 0,
    reportedSl4480: false,
  })

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

    // ---- 2. 价格异动 ----
    const bid = priceStore.bid
    if (bid > 0) {
      const deviation = Math.abs(bid - REFERENCE_PRICE)
      if (deviation > PRICE_DEVIATION) {
        const prevDev = prevState.value.reportedDeviation
        if (prevDev === 0 || Math.abs(deviation - prevDev) >= PRICE_DEVIATION) {
          const direction = bid < REFERENCE_PRICE ? '下跌' : '上涨'
          addAlert('warning',
            `价格异动：${direction} ${deviation.toFixed(1)} 点（参考 ${REFERENCE_PRICE}，当前 ${bid}）`,
            'price_deviation')
          prevState.value.reportedDeviation = deviation
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

    // ---- 4. 错误日志 ----
    try {
      const { getLogs } = await import('@/api/client')
      const logs = await getLogs('ERROR', 20)
      if (logs && logs.length > 0) {
        for (const l of logs) {
          const logKey = `log_${(l as any).id || l.time}`
          addAlert('warning',
            `日志错误: ${l.message.substring(0, 120)}`,
            logKey)
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
    prevState.value.reportedDeviation = 0
  }

  return {
    alerts, health, lastCheckTime,
    criticalCount, warningCount, unreadCount,
    runPatrol, start, stop, clearAlerts, prevState,
  }
})
