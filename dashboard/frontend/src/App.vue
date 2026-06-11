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
