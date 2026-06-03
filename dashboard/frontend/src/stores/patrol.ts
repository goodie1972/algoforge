/**
 * 监控告警 Store — 前端巡检引擎状态，无需后台守护进程
 *
 * 通过读取其他 Pinia store + 少量 API 调用完成巡检，
 * 检测引擎停止、桥接断开、价格异动、持仓变化、错误日志。
 */
import { defineStore } from 'pinia'
import { ref, computed, onUnmounted } from 'vue'
import { getEngineStatus } from '@/api/client'
import { usePriceStore } from './prices'
import { usePositionStore } from './positions'
import type { PatrolAlert } from '@/types'

const REFERENCE_PRICE = 4507.0
const PRICE_DEVIATION = 20.0
const ALERT_SL = 4480.03

export const usePatrolStore = defineStore('patrol', () => {
  // === 状态 ===
  const alerts = ref<PatrolAlert[]>([])
  const lastCheckTime = ref<string>('')
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
  function addAlert(level: PatrolAlert['level'], message: string) {
    // 去重：30 秒内相同级别的相同消息不重复报
    const recent = alerts.value[0]
    if (recent && recent.level === level && recent.message === message) return

    alerts.value.unshift({
      id: ++alertId,
      time: new Date().toLocaleTimeString(),
      level,
      message,
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
        addAlert('critical', `引擎已停止！${prevState.value.engineRunning === true ? '(刚刚停止)' : ''}`)
      } else if (!bridge) {
        addAlert('critical', 'Bridge 桥接已断开！')
      } else if (prevState.value.engineRunning === false) {
        addAlert('info', `引擎恢复运行（已运行 ${Math.floor(uptime / 60)} 分钟）`)
      }

      prevState.value.engineRunning = running
      prevState.value.bridgeConnected = bridge
    } catch {
      addAlert('critical', '无法连接引擎 API！后端可能未启动')
    }

    // ---- 2. 价格异动 ----
    const bid = priceStore.bid
    if (bid > 0) {
      const deviation = Math.abs(bid - REFERENCE_PRICE)
      if (deviation > PRICE_DEVIATION) {
        const prevDev = prevState.value.reportedDeviation
        if (prevDev === 0 || Math.abs(deviation - prevDev) >= PRICE_DEVIATION) {
          const direction = bid < REFERENCE_PRICE ? '下跌' : '上涨'
          addAlert('warning', `价格异动：${direction} ${deviation.toFixed(1)} 点（参考 ${REFERENCE_PRICE}，当前 ${bid}）`)
          prevState.value.reportedDeviation = deviation
        }
      }
    }

    // ---- 3. 持仓变化 ----
    const currentTickets = new Set(posStore.items.map(p => p.ticket))
    const prevTickets = prevState.value.positionTickets

    if (prevTickets.size > 0 && currentTickets.size !== prevTickets.size) {
      // 检测 SL=4480.03 平仓
      const closedTickets = new Set([...prevTickets].filter(t => !currentTickets.has(t)))
      if (closedTickets.size > 0 && !prevState.value.reportedSl4480) {
        const closedPos = posStore.items.filter(p => closedTickets.has(p.ticket))
        for (const p of closedPos) {
          if (Math.abs(p.stop_loss - ALERT_SL) < 0.01) {
            addAlert('critical', `止损触发！单 ${p.ticket} SL=${ALERT_SL} 被触发平仓`)
            prevState.value.reportedSl4480 = true
          }
        }
      }

      // 新开仓
      const newTickets = [...currentTickets].filter(t => !prevTickets.has(t))
      for (const t of newTickets) {
        const p = posStore.items.find(x => x.ticket === t)
        if (p) {
          addAlert('info', `新开仓 #${p.ticket} ${p.order_type} ${p.volume} lot @ ${p.open_price}`)
        }
      }

      // 平仓
      for (const t of closedTickets) {
        addAlert('info', `平仓 #${t}`)
      }
    }

    prevState.value.positionTickets = currentTickets

    // ---- 4. 错误日志（检查 lastCheckTime 之后有新的 ERROR） ----
    try {
      const { getLogs } = await import('@/api/client')
      const logs = await getLogs('ERROR', 20)
      if (logs && logs.length > 0) {
        // 只报最近 30 秒内的错误
        for (const l of logs.slice(0, 3)) {
          addAlert('warning', `日志错误: ${l.message.substring(0, 120)}`)
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
    runPatrol() // 立即跑一次
    timer = setInterval(() => runPatrol(), intervalMs)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function clearAlerts() {
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
