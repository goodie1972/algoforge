<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'
import RiskConfig from '@/components/config/RiskConfig.vue'
import ConnectionConfig from '@/components/config/ConnectionConfig.vue'
import NewsFilterConfig from '@/components/config/NewsFilterConfig.vue'
// import CoordinatorConfig from '@/components/config/CoordinatorConfig.vue'
import PaperConfig from '@/components/config/PaperConfig.vue'

const store = useConfigStore()
const message = useMessage()
const activeTab = ref('risk')

onMounted(() => store.fetch())

async function resetAll() {
  await store.reset()
  message.success('配置已重置为默认值')
}
</script>

<template>
  <n-space vertical size="large">
    <n-h2>系统配置</n-h2>
    <n-text depth="3">风控/连接/新闻/协调器修改后点击"保存"按钮提交，引擎将在下一个 tick 周期（约 60 秒内）自动生效；纸面交易配置变更即时生效</n-text>

    <n-spin v-if="store.loading" class="config-loading" />
    <n-alert v-else-if="store.error" type="error" :title="store.error" closable />
    <template v-else>
      <n-tabs v-model:value="activeTab" type="line">
        <n-tab-pane name="risk" tab="风控参数">
          <RiskConfig />
        </n-tab-pane>
        <n-tab-pane name="connection" tab="连接配置">
          <ConnectionConfig />
        </n-tab-pane>
        <n-tab-pane name="news" tab="新闻过滤">
          <NewsFilterConfig />
        </n-tab-pane>
        <n-tab-pane name="paper" tab="纸面交易">
          <PaperConfig />
        </n-tab-pane>
      </n-tabs>

      <n-button @click="resetAll" secondary type="warning" size="small">
        恢复默认设置
      </n-button>
    </template>
  </n-space>
</template>

<style scoped>
.config-loading {
  padding: 40px;
}
</style>
