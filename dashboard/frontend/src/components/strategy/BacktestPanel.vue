<script setup lang="ts">
import { ref } from 'vue'
import { useBacktestStore } from '@/stores/backtest'
import { useMessage } from 'naive-ui'
import BacktestResultView from './BacktestResultView.vue'

const backtest = useBacktestStore()
const message = useMessage()

const strategyOptions = [
  { label: 'M30 RSI+BB（当前实盘）', value: 'm30_rsi_bb' },
  { label: '— 历史策略 —', value: '' },
  { label: 'V6 Hybrid（已归档）', value: 'v6_hybrid' },
  { label: '双均线', value: 'double_ma' },
  { label: 'ATR 突破', value: 'atr_breakout' },
  { label: '双确认', value: 'combined' },
  { label: 'RSI+BB', value: 'rsi_bollinger' },
  { label: 'Stoch+BB', value: 'stoch_bollinger' },
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
    message.warning('至少选择一个策略')
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
    message.error(e?.message || '提交失败')
  }
  submitting.value = false
}
</script>

<template>
  <n-space vertical size="large">
    <n-card title="回测参数" size="small">
      <n-form label-placement="left" label-width="100" size="small">
        <n-form-item label="策略选择" required>
          <n-checkbox-group v-model:value="form.strategies">
            <n-space>
              <n-checkbox v-for="s in strategyOptions" :key="s.value" :value="s.value" :label="s.label" />
            </n-space>
          </n-checkbox-group>
        </n-form-item>

        <n-grid :cols="3" :x-gap="16">
          <n-gi>
            <n-form-item label="品种">
              <n-input value="XAUUSD" disabled size="small" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="周期">
              <n-select v-model:value="form.timeframe" :options="timeframeOptions" size="small" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="初始资金">
              <n-input-number v-model:value="form.initial_cash" :min="100" :step="1000" size="small" style="width: 100%;" />
            </n-form-item>
          </n-gi>
        </n-grid>

        <n-grid :cols="3" :x-gap="16">
          <n-gi>
            <n-form-item label="开始日期">
              <n-date-picker v-model:formatted-value="form.start_date" type="date" value-format="yyyy-MM-dd" size="small" style="width: 100%;" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="结束日期">
              <n-date-picker v-model:formatted-value="form.end_date" type="date" value-format="yyyy-MM-dd" size="small" style="width: 100%;" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="手续费/张">
              <n-input-number v-model:value="form.commission" :min="0" :step="0.1" size="small" style="width: 100%;" />
            </n-form-item>
          </n-gi>
        </n-grid>

        <n-button type="primary" :loading="submitting || backtest.loading"
                  @click="run" :disabled="backtest.loading" block>
          {{ backtest.loading ? backtest.progress || '运行中...' : '开始回测' }}
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
