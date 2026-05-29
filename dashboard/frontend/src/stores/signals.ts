import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useSignalStore = defineStore('signals', () => {
  const signal = ref<string | null>(null)
  const timestamp = ref<string | null>(null)

  function update(data: { signal: string; time?: string }) {
    signal.value = data.signal
    timestamp.value = data.time || new Date().toISOString()
  }

  return { signal, timestamp, update }
})
