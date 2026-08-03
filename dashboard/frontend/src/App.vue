<script setup lang="ts">
import { useAppStore } from './stores/app'
import { computed } from 'vue'
import AppShell from './AppShell.vue'

const appStore = useAppStore()

const themeOverrides = computed(() => ({
  common: {
    primaryColor: '#f0b90b',
    primaryColorHover: '#f5c532',
    primaryColorPressed: '#d4a309',
    primaryColorSuppl: '#e6b20a',
    fontSize: '15px',
    fontSizeSmall: '13px',
    fontSizeTiny: '12px',
    fontFamily: "'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    fontFamilyMono: "'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace",
    bodyColor: appStore.isDark ? '#0d1117' : '#f5f7fa',
    cardColor: appStore.isDark ? '#161b22' : '#ffffff',
    modalColor: appStore.isDark ? '#161b22' : '#ffffff',
    popoverColor: appStore.isDark ? '#1c2333' : '#ffffff',
    tableColor: appStore.isDark ? '#161b22' : '#ffffff',
    inputColor: appStore.isDark ? '#0d1117' : '#f5f7fa',
    actionColor: appStore.isDark ? '#1c2333' : '#f0f2f5',
    borderRadius: '10px',
    borderRadiusSmall: '6px',
    borderColor: appStore.isDark ? '#2d3139' : '#e0e4e8',
    dividerColor: appStore.isDark ? '#2d3139' : '#e0e4e8',
    hoverColor: appStore.isDark ? '#1c2333' : '#f0f2f5',
    textColor1: appStore.isDark ? '#f0f6fc' : '#1a1a2e',
    textColor2: appStore.isDark ? '#e6edf3' : '#2d2d44',
    textColor3: appStore.isDark ? '#8b949e' : '#6e7681',
    clearColor: appStore.isDark ? '#0d1117' : '#f5f7fa',
    progressRailColor: appStore.isDark ? '#2d3139' : '#e0e4e8',
  },
  Card: {
    borderRadius: '12px',
    borderColor: appStore.isDark ? '#2d3139' : '#e0e4e8',
    color: appStore.isDark ? '#161b22' : '#ffffff',
    paddingMedium: '16px 20px',
    paddingSmall: '12px 16px',
  },
  Button: {
    borderRadius: '8px',
    borderRadiusSmall: '6px',
    borderPrimary: '1px solid #f0b90b',
    colorHoverPrimary: '#f5c532',
    textColorGhost: appStore.isDark ? '#e6edf3' : '#2d2d44',
    textColorGhostHover: '#f0b90b',
  },
  Tag: { borderRadius: '6px' },
  Tabs: {
    barColor: '#f0b90b',
    tabFontSize: '14px',
    tabFontWeight: '500',
  },
  DataTable: {
    borderRadius: '10px',
    tdColor: appStore.isDark ? '#161b22' : '#ffffff',
    thColor: appStore.isDark ? '#1c2333' : '#f5f7fa',
    borderColor: appStore.isDark ? '#2d3139' : '#e0e4e8',
    thFontWeight: '600',
  },
  Menu: {
    borderRadius: '8px',
    itemColorActive: 'rgba(240, 185, 11, 0.12)',
    itemTextColorActive: '#f0b90b',
    itemIconColorActive: '#f0b90b',
    itemTextColor: appStore.isDark ? '#8b949e' : '#6e7681',
    itemIconColor: appStore.isDark ? '#8b949e' : '#6e7681',
    itemTextColorHover: appStore.isDark ? '#e6edf3' : '#1a1a2e',
    itemIconColorHover: appStore.isDark ? '#e6edf3' : '#1a1a2e',
  },
  Modal: { borderRadius: '16px' },
  Select: { menuColor: appStore.isDark ? '#1c2333' : '#ffffff' },
  Switch: { railColorActive: '#f0b90b' },
  Progress: { railColor: appStore.isDark ? '#2d3139' : '#e0e4e8' },
  Statistic: {
    labelFontSize: '13px',
    valueFontSize: '22px',
    labelFontWeight: '500',
  },
  Descriptions: {
    thColor: appStore.isDark ? '#1c2333' : '#f5f7fa',
    tdColor: appStore.isDark ? '#161b22' : '#ffffff',
    borderColor: appStore.isDark ? '#2d3139' : '#e0e4e8',
  },
  PageHeader: {
    titleFontSize: '22px',
    titleFontWeight: '600',
    subtitleFontSize: '14px',
  },
  Notification: { borderRadius: '12px' },
  Drawer: { borderRadius: '16px 0 0 16px' },
}))
</script>

<template>
  <n-config-provider :theme="appStore.naiveTheme" :theme-overrides="themeOverrides">
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
