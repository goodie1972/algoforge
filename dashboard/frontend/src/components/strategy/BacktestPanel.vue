<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useBacktestStore } from '@/stores/backtest'
import { useMessage } from 'naive-ui'
import BacktestResultView from './BacktestResultView.vue'

const { t } = useI18n()
const backtest = useBacktestStore()
const message = useMessage()

const strategyOptions = [
  { label: t('backtest.current_live'), value: 'm30_rsi_bb' },
  { label: t('backtest.history_strategies'), value: '' },
  { label: t('backtest.archived'), value: 'v6_hybrid' },
  { label: t('backtest.double_ma'), value: 'double_ma' },
  { label: t('backtest.atr_breakout'), value: 'atr_breakout' },
  { label: t('backtest.combined'), value: 'combined' },
  { label: t('backtest.rsi_bollinger'), value: 'rsi_bollinger' },
  { label: t('backtest.stoch_bollinger'), value: 'stoch_bollinger' },
]

const timeframeOptions = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1'].map(t => ({ label: t, value: t }))

const form = ref({
  strategies: ['m30_rsi_bb'] as string[],
  timeframe: 'M30',
  start_date: '2024-01-01',
  end_date: '2024-12-31',
  initial_cash: 10000,
  commission: 0.5,
})

const submitting = ref(false)

async function run() {
  if (form.value.strategies.length === 0) {
    message.warning(t('backtest.select_at_least_one'))
    return
  }
  submitting.value = true
  try {
    await backtest.submit({
      strategies: form.value.strategies,
      timeframe: form.value.timeframe,
      start_date: form.value.start_date,
      end_date: form.value.end_date,
      initial_cash: form.value.initial_cash,
      commission: form.value.commission,
    })
  } catch (e: any) {
    message.error(e?.message || t('backtest.submit_failed'))
  }
  submitting.value = false
}
</script>

<template>
  <n-space vertical size="large">
    <n-card :title="$t('backtest.parameters')" size="small">
      <n-form label-placement="left" label-width="100" size="small">
        <n-form-item :label="$t('backtest.strategy_select')" required>
          <n-checkbox-group v-model:value="form.strategies">
            <n-space>
              <n-checkbox v-for="s in strategyOptions" :key="s.value" :value="s.value" :label="s.label" />
            </n-space>
          </n-checkbox-group>
        </n-form-item>

        <n-grid :cols="3" :x-gap="16">
          <n-gi>
            <n-form-item :label="$t('backtest.symbol')">
              <n-input value="XAUUSD" disabled size="small" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item :label="$t('backtest.timeframe')">
              <n-select v-model:value="form.timeframe" :options="timeframeOptions" size="small" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item :label="$t('backtest.initial_cash')">
              <app-input-number v-model:value="form.initial_cash" :min="100" :step="1000" size="small" style="width: 100%;" />
            </n-form-item>
          </n-gi>
        </n-grid>

        <n-grid :cols="3" :x-gap="16">
          <n-gi>
            <n-form-item :label="$t('backtest.start_date')">
              <n-date-picker v-model:formatted-value="form.start_date" type="date" value-format="yyyy-MM-dd" size="small" style="width: 100%;" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item :label="$t('backtest.end_date')">
              <n-date-picker v-model:formatted-value="form.end_date" type="date" value-format="yyyy-MM-dd" size="small" style="width: 100%;" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item :label="$t('backtest.commission')">
              <app-input-number v-model:value="form.commission" :min="0" :step="0.1" size="small" style="width: 100%;" />
            </n-form-item>
          </n-gi>
        </n-grid>

        <n-button type="primary" :loading="submitting || backtest.loading"
                  @click="run" :disabled="backtest.loading" block>
          {{ backtest.loading ? backtest.progress || $t('backtest.running') : $t('backtest.run_backtest') }}
        </n-button>
      </n-form>

      <!-- 错误 -->
      <n-alert v-if="backtest.error" type="error" :title="backtest.error" closable
               style="margin-top: 12px;" @close="backtest.reset()" />
    </n-card>

    <!-- 回测结果 -->
    <BacktestResultView v-if="backtest.result" :result="backtest.result" />
  </n-space>
</template>
