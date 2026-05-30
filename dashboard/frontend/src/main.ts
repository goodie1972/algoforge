import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(naive)

// 确保路由器完成初始导航后再挂载
// 解决 createWebHistory 在 Vite 下初次 URL 不匹配的问题
router.isReady().then(() => {
  app.mount('#app')
})
