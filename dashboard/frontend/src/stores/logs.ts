import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getLogs } from '@/api/client'
import type { LogEntry } from '@/types'

export const useLogStore = defineStore('logs', () => {
  const entries = ref<LogEntry[]>([])
  const filterLevel = ref<string | null>(null)
  const maxEntries = 500

  const filteredEntries = computed(() => {
    if (!filterLevel.value) return entries.value
    const levels = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3 }
    const min = levels[filterLevel.value as keyof typeof levels] ?? 0
    return entries.value.filter(e => (levels[e.level as keyof typeof levels] ?? 0) >= min)
  })

  function append(entry: LogEntry) {
    entries.value.push(entry)
    if (entries.value.length > maxEntries) {
      entries.value = entries.value.slice(-maxEntries)
    }
  }

  async function fetchHistory(level?: string, limit = 100) {
    try {
      const logs = await getLogs(level, limit)
      const existing = new Set(entries.value.map(e => e.time + e.message))
      for (const log of logs) {
        if (!existing.has(log.time + log.message)) {
          entries.value.push(log)
        }
      }
      if (entries.value.length > maxEntries) {
        entries.value = entries.value.slice(-maxEntries)
      }
    } catch { /* ignore */ }
  }

  function clear() {
    entries.value = []
  }

  return { entries, filterLevel, filteredEntries, append, fetchHistory, clear }
})
