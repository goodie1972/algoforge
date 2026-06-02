import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { runBacktest, getBacktestStatus, getBacktestResults, getBacktestHistory } from '@/api/client'
import type { BacktestRequest, BacktestResult, BacktestHistoryItem } from '@/types'

export const useBacktestStore = defineStore('backtest', () => {
  const jobId = ref<string | null>(null)
  const status = ref<'idle' | 'queued' | 'running' | 'completed' | 'failed'>('idle')
  const progress = ref('')
  const error = ref<string | null>(null)
  const result = ref<BacktestResult | null>(null)
  const history = ref<BacktestHistoryItem[]>([])

  const loading = computed(() => status.value === 'queued' || status.value === 'running')

  let pollTimer: ReturnType<typeof setInterval> | null = null

  async function submit(params: BacktestRequest) {
    status.value = 'queued'
    progress.value = '提交中...'
    error.value = null
    result.value = null

    try {
      const res = await runBacktest(params)
      jobId.value = res.job_id
      status.value = 'queued'
      progress.value = '排队中...'
      startPolling()
    } catch (e: any) {
      status.value = 'failed'
      error.value = e?.response?.data?.detail || e?.message || '提交回测失败'
    }
  }

  function startPolling() {
    stopPolling()
    pollTimer = setInterval(async () => {
      if (!jobId.value) return
      try {
        const s = await getBacktestStatus(jobId.value)
        status.value = s.status as any
        progress.value = s.progress || ''
        if (s.error) error.value = s.error
        if (s.status === 'completed') {
          stopPolling()
          await loadResults()
        } else if (s.status === 'failed') {
          stopPolling()
          error.value = s.error || '回测失败'
        }
      } catch {
        // ignore polling errors
      }
    }, 1000)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  async function loadResults() {
    if (!jobId.value) return
    try {
      const res = await getBacktestResults(jobId.value)
      if (res.result) result.value = res.result
    } catch { /* ignore */ }
  }

  async function fetchHistory() {
    try {
      history.value = await getBacktestHistory()
    } catch { /* ignore */ }
  }

  function reset() {
    stopPolling()
    jobId.value = null
    status.value = 'idle'
    progress.value = ''
    error.value = null
    result.value = null
  }

  return {
    jobId, status, progress, error, result, history,
    loading,
    submit, fetchHistory, loadResults, reset,
  }
})
