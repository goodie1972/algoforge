<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'
import RiskConfig from '@/components/config/RiskConfig.vue'
import ConnectionConfig from '@/components/config/ConnectionConfig.vue'
import NewsFilterConfig from '@/components/config/NewsFilterConfig.vue'
// import CoordinatorConfig from '@/components/config/CoordinatorConfig.vue'
import PaperConfig from '@/components/config/PaperConfig.vue'
import AiAgentConfig from '@/components/config/AiAgentConfig.vue'

const store = useConfigStore()
const message = useMessage()
const { t } = useI18n()
const activeTab = ref('risk')

onMounted(() => store.fetch())

async function resetAll() {
  await store.reset()
  message.success(t('config.reset_done'))
}
</script>

<template>
  <n-space vertical size="large">
    <n-h2>{{ t('config.title') }}</n-h2>
    <n-text depth="3">{{ t('config.desc') }}</n-text>

    <n-spin v-if="store.loading" class="config-loading" />
    <n-alert v-else-if="store.error" type="error" :title="store.error" closable />
    <template v-else>
      <n-tabs v-model:value="activeTab" type="line">
        <n-tab-pane name="risk" :tab="t('config.tab_risk')">
          <RiskConfig />
        </n-tab-pane>
        <n-tab-pane name="connection" :tab="t('config.tab_connection')">
          <ConnectionConfig />
        </n-tab-pane>
        <n-tab-pane name="news" :tab="t('config.tab_news')">
          <NewsFilterConfig />
        </n-tab-pane>
        <n-tab-pane name="paper" :tab="t('config.tab_paper')">
          <PaperConfig />
        </n-tab-pane>
        <n-tab-pane name="ai" :tab="t('config.tab_ai')">
          <AiAgentConfig />
        </n-tab-pane>
      </n-tabs>

      <n-button @click="resetAll" secondary type="warning" size="small">
        {{ t('config.reset') }}
      </n-button>
    </template>
  </n-space>
</template>

<style scoped>
.config-loading {
  padding: 40px;
}
</style>
