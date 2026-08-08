<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'

const { t } = useI18n()
const store = useConfigStore()
const message = useMessage()

const sensitivityOptions = computed(() => [
  { label: t('coordinator.trigger_rate_disabled'), value: 0 },
  { label: t('coordinator.trigger_rate', { value: '0.1', pct: '82' }), value: 0.1 },
  { label: t('coordinator.trigger_rate', { value: '0.2', pct: '63' }), value: 0.2 },
  { label: t('coordinator.trigger_rate', { value: '0.3', pct: '50' }), value: 0.3 },
  { label: t('coordinator.trigger_rate', { value: '0.4', pct: '38' }), value: 0.4 },
  { label: t('coordinator.trigger_rate_recommended', { value: '0.5', pct: '25' }), value: 0.5 },
  { label: t('coordinator.trigger_rate', { value: '0.6', pct: '19' }), value: 0.6 },
  { label: t('coordinator.trigger_rate', { value: '0.7', pct: '14' }), value: 0.7 },
  { label: t('coordinator.trigger_rate', { value: '0.8', pct: '10' }), value: 0.8 },
  { label: t('coordinator.trigger_rate', { value: '0.9', pct: '5' }), value: 0.9 },
  { label: t('coordinator.trigger_rate', { value: '1.0', pct: '2' }), value: 1.0 },
])

function defaults() {
  return {
    enabled: store.items?.coordinator?.enabled ?? false,
    m15_reverse_tp_enabled: store.items?.coordinator?.m15_reverse_tp_enabled ?? false,
    m15_reverse_tp_sensitivity: store.items?.coordinator?.m15_reverse_tp_sensitivity ?? 0.5,
    mtf_resonance_enabled: store.items?.coordinator?.mtf_resonance_enabled ?? false,
    position_gate_enabled: store.items?.coordinator?.position_gate_enabled ?? true,
    position_gate_lookback: store.items?.coordinator?.position_gate_lookback ?? 60,
    position_gate_m30_lookback: store.items?.coordinator?.position_gate_m30_lookback ?? 40,
    position_gate_bottom: store.items?.coordinator?.position_gate_bottom ?? 0.10,
    position_gate_top: store.items?.coordinator?.position_gate_top ?? 0.90,
    rally_drop_enabled: store.items?.coordinator?.rally_drop_enabled ?? true,
    rally_drop_lookback: store.items?.coordinator?.rally_drop_lookback ?? 30,
    rally_drop_threshold: store.items?.coordinator?.rally_drop_threshold ?? 1.5,
    di_gate_skip_threshold: store.items?.coordinator?.di_gate_skip_threshold ?? 20,
    rally_drop_adx_skip: store.items?.coordinator?.rally_drop_adx_skip ?? 25,
    profit_drawdown_enabled: store.items?.coordinator?.profit_drawdown_enabled ?? true,
    profit_drawdown_pct: store.items?.coordinator?.profit_drawdown_pct ?? 0.25,
    profit_drawdown_min_peak_atr: store.items?.coordinator?.profit_drawdown_min_peak_atr ?? 0.5,
  }
}

const local = reactive(defaults())

const original = computed(() => defaults())
const changed = computed(() => JSON.stringify(local) !== JSON.stringify(original.value))

watch(() => store.items?.coordinator, () => Object.assign(local, defaults()), { deep: true })

async function save() {
  await store.updateCoordinator({ ...local })
  message.success(t('coordinator.saved'))
}
</script>

<template>
  <n-space vertical size="medium">
    <n-grid :cols="2" :x-gap="24" :y-gap="12">
      <!-- 左列 -->
      <n-grid-item>
        <n-space vertical size="medium">
          <n-form-item :label="t('coordinator.enable')">
            <n-switch :value="local.enabled"
              @update:value="(v: boolean) => local.enabled = v" />
            <template #feedback>{{ t('coordinator.enable_feedback') }}</template>
          </n-form-item>

          <template v-if="local.enabled">
            <n-divider title-position="left">{{ t('coordinator.rules') }}</n-divider>
            <n-alert type="info" :bordered="false" style="font-size: 13px;">
              <div v-if="local.position_gate_enabled">
                <n-text code>① {{ t('coordinator.position_gate') }}</n-text>：{{ t('coordinator.position_gate_desc1', { lookback: local.position_gate_m30_lookback, bottom: (local.position_gate_bottom * 100).toFixed(0), top: (local.position_gate_top * 100).toFixed(0) }) }}。{{ t('coordinator.position_gate_desc2', { threshold: local.di_gate_skip_threshold }) }}。<br>
              </div>
              <div v-if="local.rally_drop_enabled">
                <n-text code>② {{ t('coordinator.rally_drop') }}</n-text>：{{ t('coordinator.rally_drop_desc1', { threshold: local.rally_drop_threshold, adx: local.rally_drop_adx_skip }) }}。<br>
              </div>
              <div v-if="local.profit_drawdown_enabled">
                <n-text code>③ {{ t('coordinator.profit_drawdown') }}</n-text>：{{ t('coordinator.profit_drawdown_desc', { pct: (local.profit_drawdown_pct * 100).toFixed(0) }) }}。
              </div>
            </n-alert>
          </template>
        </n-space>
      </n-grid-item>

      <!-- 右列 -->
      <n-grid-item>
        <n-space vertical size="medium">
          <template v-if="local.enabled">
            <n-divider title-position="left">{{ t('coordinator.exit_section') }}</n-divider>
            <n-form-item :label="t('coordinator.m15_reverse_tp')">
              <n-switch :value="local.m15_reverse_tp_enabled"
                @update:value="(v: boolean) => local.m15_reverse_tp_enabled = v" />
            </n-form-item>
            <template v-if="local.m15_reverse_tp_enabled">
              <n-form-item :label="t('coordinator.sensitivity')">
                <n-select :value="local.m15_reverse_tp_sensitivity" :options="sensitivityOptions"
                  @update:value="(v: number) => local.m15_reverse_tp_sensitivity = v"
                  style="width: 100%;" />
              </n-form-item>
            </template>

            <n-divider title-position="left">{{ t('coordinator.func2_title') }}</n-divider>
            <n-form-item :label="t('coordinator.func2_label')">
              <n-switch :value="local.mtf_resonance_enabled"
                @update:value="(v: boolean) => local.mtf_resonance_enabled = v" />
            </n-form-item>

            <n-divider title-position="left">{{ t('coordinator.func3_title') }}</n-divider>

            <!-- 位置门禁 -->
            <n-card size="small" :segmented="{ content: true }" style="margin-bottom: 8px;">
              <template #header>
                <n-space align="center" style="display: flex; justify-content: space-between;">
                  <span style="font-weight: 600;">① {{ t('coordinator.position_gate') }}</span>
                  <n-switch :value="local.position_gate_enabled"
                    @update:value="(v: boolean) => local.position_gate_enabled = v" />
                </n-space>
              </template>
              <template v-if="local.position_gate_enabled">
                <n-form-item :label="t('coordinator.m30_lookback')" label-placement="left" :label-width="110">
                  <app-input-number :value="local.position_gate_m30_lookback"
                    @update:value="(v: number) => local.position_gate_m30_lookback = v"
                    :min="10" :max="200" style="width: 110px;" />
                </n-form-item>
                <n-grid :cols="2" :x-gap="8">
                  <n-grid-item>
                    <n-form-item :label="t('coordinator.bottom_threshold')" label-placement="left" :label-width="80">
                      <app-input-number :value="local.position_gate_bottom"
                        @update:value="(v: number) => local.position_gate_bottom = v"
                        :min="0.01" :max="0.50" :step="0.01" style="width: 90px;" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item :label="t('coordinator.top_threshold')" label-placement="left" :label-width="80">
                      <app-input-number :value="local.position_gate_top"
                        @update:value="(v: number) => local.position_gate_top = v"
                        :min="0.50" :max="0.99" :step="0.01" style="width: 90px;" />
                    </n-form-item>
                  </n-grid-item>
                </n-grid>
                <n-form-item :label="t('coordinator.di_gate_skip')" label-placement="left" :label-width="110">
                  <app-input-number :value="local.di_gate_skip_threshold"
                    @update:value="(v: number) => local.di_gate_skip_threshold = v"
                    :min="5" :max="100" style="width: 110px;" />
                  <template #feedback>{{ t('coordinator.di_gate_skip_desc') }}</template>
                </n-form-item>
              </template>
            </n-card>

            <!-- 急跌急涨 -->
            <n-card size="small" :segmented="{ content: true }" style="margin-bottom: 8px;">
              <template #header>
                <n-space align="center" style="display: flex; justify-content: space-between;">
                  <span style="font-weight: 600;">② {{ t('coordinator.rally_drop_penalty') }}</span>
                  <n-switch :value="local.rally_drop_enabled"
                    @update:value="(v: boolean) => local.rally_drop_enabled = v" />
                </n-space>
              </template>
              <template v-if="local.rally_drop_enabled">
                <n-form-item :label="t('coordinator.lookback')" label-placement="left" :label-width="110">
                  <app-input-number :value="local.rally_drop_lookback"
                    @update:value="(v: number) => local.rally_drop_lookback = v"
                    :min="5" :max="100" style="width: 110px;" />
                </n-form-item>
                <n-form-item :label="t('coordinator.threshold_pct')" label-placement="left" :label-width="110">
                  <app-input-number :value="local.rally_drop_threshold"
                    @update:value="(v: number) => local.rally_drop_threshold = v"
                    :min="0.1" :max="5.0" :step="0.1" style="width: 110px;" />
                </n-form-item>
                <n-form-item :label="t('coordinator.adx_skip')" label-placement="left" :label-width="110">
                  <app-input-number :value="local.rally_drop_adx_skip"
                    @update:value="(v: number) => local.rally_drop_adx_skip = v"
                    :min="10" :max="60" style="width: 110px;" />
                  <template #feedback>{{ t('coordinator.adx_skip_desc') }}</template>
                </n-form-item>
              </template>
            </n-card>

            <!-- 回撤止盈 -->
            <n-card size="small" :segmented="{ content: true }" style="margin-bottom: 8px;">
              <template #header>
                <n-space align="center" style="display: flex; justify-content: space-between;">
                  <span style="font-weight: 600;">③ {{ t('coordinator.profit_drawdown') }}</span>
                  <n-switch :value="local.profit_drawdown_enabled"
                    @update:value="(v: boolean) => local.profit_drawdown_enabled = v" />
                </n-space>
              </template>
              <template v-if="local.profit_drawdown_enabled">
                <n-form-item :label="t('coordinator.drawdown_pct')" label-placement="left" :label-width="110">
                  <app-input-number :value="local.profit_drawdown_pct"
                    @update:value="(v: number) => local.profit_drawdown_pct = v"
                    :min="0.05" :max="1.0" :step="0.05" style="width: 110px;" />
                </n-form-item>
                <n-form-item :label="t('coordinator.peak_atr')" label-placement="left" :label-width="110">
                  <app-input-number :value="local.profit_drawdown_min_peak_atr"
                    @update:value="(v: number) => local.profit_drawdown_min_peak_atr = v"
                    :min="0.0" :max="5.0" :step="0.1" style="width: 110px;" />
                </n-form-item>
              </template>
            </n-card>

          </template>
        </n-space>
      </n-grid-item>
    </n-grid>

    <n-button type="primary" :disabled="!changed" @click="save" block>
      {{ t('coordinator.save_btn') }}
    </n-button>
  </n-space>
</template>
