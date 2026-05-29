<script setup lang="ts">
import { useConfigStore } from '@/stores/config'
const store = useConfigStore()
</script>

<template>
  <n-alert type="info" :bordered="false" style="margin-bottom: 16px;">
    MT4 连接参数在 <n-tag size="small">config/settings.py</n-tag> 中配置，修改后重启引擎生效。
  </n-alert>
  <n-descriptions :column="1" label-placement="left" bordered size="small">
    <n-descriptions-item label="MT4 地址">127.0.0.1:23232</n-descriptions-item>
    <n-descriptions-item label="交易品种">XAUUSD</n-descriptions-item>
    <n-descriptions-item label="Magic Number">
      <n-tag size="small">{{ store.items.magic_number || 888888 }}</n-tag>
    </n-descriptions-item>
    <n-descriptions-item label="K 线周期">
      <n-tag size="small">{{ store.items.timeframe || 'H1' }}</n-tag>
    </n-descriptions-item>
  </n-descriptions>
</template>
