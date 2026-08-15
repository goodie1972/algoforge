import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:1783',
        changeOrigin: true,
      },
      '/ws': {
        target: 'http://127.0.0.1:1783',
        ws: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router', 'pinia'],
          'vendor-charts': ['lightweight-charts'],
          'vendor-naive': ['naive-ui'],
          'vendor-i18n': ['vue-i18n'],
        },
      },
    },
    chunkSizeWarningLimit: 600,
  },
})
