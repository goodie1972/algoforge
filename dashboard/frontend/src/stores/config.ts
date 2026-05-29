import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getConfig, updateConfig, resetConfig, getStrategyPool, updateStrategyPool as updatePoolApi } from '@/api/client'

export const useConfigStore = defineStore('config', () => {
  const items = ref<Record<string, any>>({})
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      items.value = await getConfig()
    } catch (e: any) {
      error.value = e?.message || '获取配置失败'
    } finally {
      loading.value = false
    }
  }

  async function fetchConfig() { await fetch() }

  async function update(updates: Record<string, any>) {
    error.value = null
    try {
      await updateConfig(updates)
      await fetch()
    } catch (e: any) {
      error.value = e?.message || '更新配置失败'
    }
  }

  async function updateStrategyPool(pool: Record<string, any>) {
    error.value = null
    try {
      await updatePoolApi(pool)
      await fetch()
    } catch (e: any) {
      error.value = e?.message || '更新策略池失败'
      throw e
    }
  }

  async function fetchStrategyPool() {
    try {
      return await getStrategyPool()
    } catch (e: any) {
      error.value = e?.message || '获取策略池失败'
      return null
    }
  }

  async function reset(key?: string) {
    await resetConfig(key)
    await fetch()
  }

  return { items, loading, error, fetch, fetchConfig, update, updateStrategyPool, fetchStrategyPool, reset }
})
