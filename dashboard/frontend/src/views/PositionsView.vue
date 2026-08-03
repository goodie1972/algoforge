<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePositionStore } from '@/stores/positions'
import { useAccountStore } from '@/stores/account'
import { useTradeStore } from '@/stores/trades'
import { NButton, NTag, NSpace, NCard, NModal } from 'naive-ui'
import AccountPanel from '@/components/dashboard/AccountPanel.vue'
import PositionsTableBase from '@/components/dashboard/PositionsTableBase.vue'
import TradeHistoryTableBase from '@/components/dashboard/TradeHistoryTableBase.vue'

const store = usePositionStore()
const account = useAccountStore()
const tradeStore = useTradeStore()
const { t } = useI18n()
const showHistoryModal = ref(false)
const fullHistory = ref<any[]>([])
const loadingFullHistory = ref(false)

onMounted(() => tradeStore.fetch(10))

async function openFullHistory() {
  showHistoryModal.value = true
  loadingFullHistory.value = true
  try {
    const { getTradeHistory } = await import('@/api/client')
    fullHistory.value = await getTradeHistory(999)
  } catch { /* ignore */ }
  finally { loadingFullHistory.value = false }
}
</script>

<template>
  <n-space vertical size="large">
    <AccountPanel />

    <div class="positions-header">
      <n-h2 class="positions-title">{{ t('positions.title') }}</n-h2>
      <n-space size="small">
        <n-tag :bordered="false" type="success">{{ t('positions.long') }} {{ store.longCount }}</n-tag>
        <n-tag :bordered="false" type="error">{{ t('positions.short') }} {{ store.shortCount }}</n-tag>
        <n-tag :bordered="false" :type="store.totalProfit >= 0 ? 'success' : 'error'">
          {{ t('positions.summary') }} ${{ store.totalProfit.toFixed(2) }}
        </n-tag>
      </n-space>
    </div>

    <PositionsTableBase />

    <!-- 最近成交 -->
    <n-card :title="t('positions.recent_trades')" size="small">
      <template #header-extra>
        <n-space size="small">
          <n-tag :bordered="false" type="info">{{ t('positions.total_trades', {count: tradeStore.items.length}) }}</n-tag>
          <n-button size="tiny" secondary circle type="primary" @click="openFullHistory">
            <template #icon><span class="history-more-icon">+</span></template>
          </n-button>
        </n-space>
      </template>
      <TradeHistoryTableBase :items="tradeStore.items" :loading="tradeStore.loading" :error="tradeStore.error" :max-height="240" />
    </n-card>

    <!-- 全部历史成交弹窗 -->
    <n-modal v-model:show="showHistoryModal" preset="card" :title="t('positions.all_history')"
             :style="{ maxWidth: '95vw', maxHeight: '90vh' }" size="large" closable>
      <TradeHistoryTableBase :items="fullHistory" :loading="loadingFullHistory" :max-height="560" />
    </n-modal>
  </n-space>
</template>

<style scoped>
.positions-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.positions-title {
  margin: 0;
}
.history-more-icon {
  font-weight: bold;
  font-size: 16px;
}
</style>
