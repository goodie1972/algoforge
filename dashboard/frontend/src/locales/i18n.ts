import { createI18n } from 'vue-i18n'
import zhCN from './zh-CN.json'
import enUS from './en-US.json'

const messages = {
  'zh-CN': zhCN,
  'en-US': enUS,
}

const i18n = createI18n({
  locale: localStorage.getItem('algoforge-lang') || 'zh-CN',
  fallbackLocale: 'en-US',
  messages,
  legacy: true,
  globalInjection: true,
})

export default i18n