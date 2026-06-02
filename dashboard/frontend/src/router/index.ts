import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
    },
    {
      path: '/positions',
      name: 'positions',
      component: () => import('@/views/PositionsView.vue'),
    },
    {
      path: '/strategies',
      name: 'strategies',
      component: () => import('@/views/StrategyCenterView.vue'),
    },
    {
      path: '/config',
      name: 'config',
      component: () => import('@/views/ConfigView.vue'),
    },
    {
      path: '/logs',
      name: 'logs',
      component: () => import('@/views/LogViewer.vue'),
    },
    {
      path: '/trades',
      name: 'trades',
      component: () => import('@/views/TradeHistoryView.vue'),
    },
  ],
})

export default router
