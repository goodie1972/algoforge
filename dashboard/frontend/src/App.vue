<script setup lang="ts">
import { darkTheme } from 'naive-ui'
import AppShell from './AppShell.vue'

const themeOverrides = {
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
    bodyColor: '#0d1117',
    cardColor: '#161b22',
    modalColor: '#161b22',
    popoverColor: '#1c2333',
    tableColor: '#161b22',
    inputColor: '#0d1117',
    actionColor: '#1c2333',
    borderRadius: '10px',
    borderRadiusSmall: '6px',
    borderColor: '#2d3139',
    dividerColor: '#2d3139',
    hoverColor: '#1c2333',
    textColor1: '#e6edf3',
    textColor2: '#c9d1d9',
    textColor3: '#8b949e',
    clearColor: '#0d1117',
    progressRailColor: '#2d3139',
  },
  Card: {
    borderRadius: '12px',
    borderColor: '#2d3139',
    color: '#161b22',
    paddingMedium: '16px 20px',
    paddingSmall: '12px 16px',
  },
  Button: {
    borderRadius: '8px',
    borderRadiusSmall: '6px',
    borderPrimary: '1px solid #f0b90b',
    colorHoverPrimary: '#f5c532',
    textColorGhost: '#e6edf3',
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
    tdColor: '#161b22',
    thColor: '#1c2333',
    borderColor: '#2d3139',
    thFontWeight: '600',
  },
  Menu: {
    borderRadius: '8px',
    itemColorActive: 'rgba(240, 185, 11, 0.12)',
    itemTextColorActive: '#f0b90b',
    itemIconColorActive: '#f0b90b',
    itemTextColor: '#8b949e',
    itemIconColor: '#8b949e',
    itemTextColorHover: '#e6edf3',
    itemIconColorHover: '#e6edf3',
  },
  Modal: { borderRadius: '16px' },
  Select: { menuColor: '#1c2333' },
  Switch: { railColorActive: '#f0b90b' },
  Progress: { railColor: '#2d3139' },
  Statistic: {
    labelFontSize: '13px',
    valueFontSize: '22px',
    labelFontWeight: '500',
  },
  Descriptions: {
    thColor: '#1c2333',
    tdColor: '#161b22',
    borderColor: '#2d3139',
  },
  PageHeader: {
    titleFontSize: '22px',
    titleFontWeight: '600',
    subtitleFontSize: '14px',
  },
  Notification: { borderRadius: '12px' },
  Drawer: { borderRadius: '16px 0 0 16px' },
}
</script>

<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="themeOverrides">
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
