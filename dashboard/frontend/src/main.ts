import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import './style.css'
import App from './App.vue'
import router from './router'
import AppInputNumber from './components/config/AppInputNumber.vue'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(naive)
// 全局注册自定义输入框组件（使用 Tabler chevron 图标替换 Naive UI 的 +/- 按钮）
app.component('app-input-number', AppInputNumber)

// 确保路由器完成初始导航后再挂载
// 解决 createWebHistory 在 Vite 下初次 URL 不匹配的问题
router.isReady().then(() => {
  app.mount('#app')
})