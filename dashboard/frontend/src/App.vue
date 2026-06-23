<script setup lang="ts">
import { darkTheme } from 'naive-ui'
import AppShell from './AppShell.vue'
</script>

<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="{
    common: { primaryColor: '#f0b90b', primaryColorHover: '#f5c532', primaryColorPressed: '#d4a309', fontSize: '15px' }
  }">
    <n-message-provider>
      <n-notification-provider>
        <n-dialog-provider>
          <AppShell />
        </n-dialog-provider>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style>
/* 全局替换 InputNumber +/- 图标为上下箭头 */
.n-input-number .n-button--primary-type .n-icon svg {
  display: none !important;
}
.n-input-number .n-button--primary-type:first-child .n-button__content::after {
  content: '▲' !important;
  font-size: 10px !important;
}
.n-input-number .n-button--primary-type:last-child .n-button__content::after {
  content: '▼' !important;
  font-size: 10px !important;
}
</style>
