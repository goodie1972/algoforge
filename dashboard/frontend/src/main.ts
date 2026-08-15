import { createApp } from 'vue'
import { createPinia } from 'pinia'
import i18n from './locales/i18n'
import './style.css'
import App from './App.vue'
import router from './router'
import AppInputNumber from './components/config/AppInputNumber.vue'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(i18n)
// 全局注册自定义输入框组件
app.component('app-input-number', AppInputNumber)

router.isReady().then(() => {
  app.mount('#app')
})