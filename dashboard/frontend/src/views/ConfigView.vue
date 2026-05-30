<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'
import StrategyConfig from '@/components/config/StrategyConfig.vue'
import RiskConfig from '@/components/config/RiskConfig.vue'
import ConnectionConfig from '@/components/config/ConnectionConfig.vue'
import NewsFilterConfig from '@/components/config/NewsFilterConfig.vue'

const store = useConfigStore()
const message = useMessage()
const activeTab = ref('strategy')

onMounted(() => store.fetch())

async function resetAll() {
  await store.reset()
  message.success('配置已重置为默认值')
}
</script>

<template>
  <n-space vertical size="large">
    <n-h2>运行时配置</n-h2>
    <n-text depth="3">修改后自动保存，引擎将在下一个 tick 周期（约 60 秒内）自动生效</n-text>

    <n-spin v-if="store.loading" style="padding: 40px;" />
    <n-alert v-else-if="store.error" type="error" :title="store.error" closable />
    <template v-else>
      <n-tabs v-model:value="activeTab" type="line" animated>
        <n-tab-pane name="strategy" tab="策略参数">
          <StrategyConfig />
        </n-tab-pane>
        <n-tab-pane name="risk" tab="风控参数">
          <RiskConfig />
        </n-tab-pane>
        <n-tab-pane name="connection" tab="连接配置">
          <ConnectionConfig />
        </n-tab-pane>
        <n-tab-pane name="news" tab="新闻过滤">
          <NewsFilterConfig />
        </n-tab-pane>
      </n-tabs>

      <n-button @click="resetAll" secondary type="warning" size="small">
        恢复默认设置
      </n-button>
    </template>
  </n-space>
</template>
