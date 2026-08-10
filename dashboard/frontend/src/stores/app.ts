import { ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { darkTheme, lightTheme } from 'naive-ui'

export const useAppStore = defineStore('app', () => {
  const theme = ref<'dark' | 'light'>(
    (localStorage.getItem('algoforge-theme') as 'dark' | 'light') || 'dark'
  )
  const locale = ref<string>(
    localStorage.getItem('algoforge-lang') || 'zh-CN'
  )

  const naiveTheme = ref(darkTheme)
  const isDark = ref(true)

  watch(theme, (val) => {
    localStorage.setItem('algoforge-theme', val)
    naiveTheme.value = val === 'dark' ? darkTheme : lightTheme
    isDark.value = val === 'dark'
    document.documentElement.setAttribute('data-theme', val)
  }, { immediate: true })

  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  function setLocale(lang: string) {
    locale.value = lang
    localStorage.setItem('algoforge-lang', lang)
    // 通知后端切换日志语言（静默失败即可）
    import('@/api/client').then(({ updateConfig }) => {
      updateConfig({ language: lang }).catch(() => {})
    })
  }

  return { theme, locale, naiveTheme, isDark, toggleTheme, setLocale }
})