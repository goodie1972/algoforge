<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()

const sensitivityOptions = [
  { label: '0.0 (关闭归一化, 原版敏感逻辑)', value: 0 },
  { label: '0.1 (触发率 82%)', value: 0.1 },
  { label: '0.2 (触发率 63%)', value: 0.2 },
  { label: '0.3 (触发率 50%)', value: 0.3 },
  { label: '0.4 (触发率 38%)', value: 0.4 },
  { label: '0.5 (触发率 25%, 推荐)', value: 0.5 },
  { label: '0.6 (触发率 19%)', value: 0.6 },
  { label: '0.7 (触发率 14%)', value: 0.7 },
  { label: '0.8 (触发率 10%)', value: 0.8 },
  { label: '0.9 (触发率 5%)', value: 0.9 },
  { label: '1.0 (触发率 2%)', value: 1.0 },
]

function defaults() {
  return {
    enabled: store.items?.coordinator?.enabled ?? false,
    m15_reverse_tp_enabled: store.items?.coordinator?.m15_reverse_tp_enabled ?? false,
    m15_reverse_tp_sensitivity: store.items?.coordinator?.m15_reverse_tp_sensitivity ?? 0.5,
    mtf_resonance_enabled: store.items?.coordinator?.mtf_resonance_enabled ?? false,
    position_gate_enabled: store.items?.coordinator?.position_gate_enabled ?? true,
    position_gate_lookback: store.items?.coordinator?.position_gate_lookback ?? 60,
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
  message.success('协调器配置已保存')
}
</script>

<template>
  <n-space vertical size="medium">
    <n-grid :cols="2" :x-gap="24" :y-gap="12">
      <!-- 左列 -->
      <n-grid-item>
        <n-space vertical size="medium">
          <n-form-item label="启用协调器">
            <n-switch :value="local.enabled"
              @update:value="(v: boolean) => local.enabled = v" />
            <template #feedback>开启后启用下方 K 线过滤器功能</template>
          </n-form-item>

          <template v-if="local.enabled">
            <n-divider title-position="left">规则说明</n-divider>
            <n-alert type="info" :bordered="false" style="font-size: 13px;">
              <div v-if="local.position_gate_enabled">
                <n-text code>① 位置门禁</n-text>：价格在 {{ local.position_gate_lookback }} 根 K 线区间的底部 {{ (local.position_gate_bottom * 100).toFixed(0) }}% / 顶部 {{ (local.position_gate_top * 100).toFixed(0) }}% 时，禁止对应方向开仓。DI 差值 > {{ local.di_gate_skip_threshold }} 时跳过。<br>
              </div>
              <div v-if="local.rally_drop_enabled">
                <n-text code>② 急跌急涨</n-text>：M30 周期内从高点回落超过 {{ local.rally_drop_threshold }}% 禁追空、从低点上涨超过 {{ local.rally_drop_threshold }}% 禁追多。ADX > {{ local.rally_drop_adx_skip }} 时跳过。<br>
              </div>
              <div v-if="local.profit_drawdown_enabled">
                <n-text code>③ 回撤止盈</n-text>：浮动盈利从峰值回撤 {{ (local.profit_drawdown_pct * 100).toFixed(0) }}% 即止盈。
              </div>
            </n-alert>
          </template>
        </n-space>
      </n-grid-item>

      <!-- 右列 -->
      <n-grid-item>
        <n-space vertical size="medium">
          <template v-if="local.enabled">
            <n-divider title-position="left">功能①：M15 反向止盈</n-divider>
            <n-form-item label="M15 反向止盈">
              <n-switch :value="local.m15_reverse_tp_enabled"
                @update:value="(v: boolean) => local.m15_reverse_tp_enabled = v" />
            </n-form-item>
            <template v-if="local.m15_reverse_tp_enabled">
              <n-form-item label="灵敏度">
                <n-select :value="local.m15_reverse_tp_sensitivity" :options="sensitivityOptions"
                  @update:value="(v: number) => local.m15_reverse_tp_sensitivity = v"
                  style="width: 100%;" />
              </n-form-item>
            </template>

            <n-divider title-position="left">功能②：H1+M15 共振方向门禁</n-divider>
            <n-form-item label="启用共振门禁">
              <n-switch :value="local.mtf_resonance_enabled"
                @update:value="(v: boolean) => local.mtf_resonance_enabled = v" />
            </n-form-item>

            <n-divider title-position="left">功能③：K线过滤器</n-divider>

            <!-- 位置门禁 -->
            <n-card size="small" :segmented="{ content: true }" style="margin-bottom: 8px;">
              <template #header>
                <n-space align="center" style="display: flex; justify-content: space-between;">
                  <span style="font-weight: 600;">① 位置门禁</span>
                  <n-switch :value="local.position_gate_enabled"
                    @update:value="(v: boolean) => local.position_gate_enabled = v" />
                </n-space>
              </template>
              <template v-if="local.position_gate_enabled">
                <n-form-item label="区间周期（K线）" label-placement="left" :label-width="110">
                  <n-input-number :value="local.position_gate_lookback"
                    @update:value="(v: number) => local.position_gate_lookback = v"
                    :min="10" :max="200" style="width: 110px;" />
                </n-form-item>
                <n-grid :cols="2" :x-gap="8">
                  <n-grid-item>
                    <n-form-item label="底部阈值" label-placement="left" :label-width="80">
                      <n-input-number :value="local.position_gate_bottom"
                        @update:value="(v: number) => local.position_gate_bottom = v"
                        :min="0.01" :max="0.50" :step="0.01" style="width: 90px;" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item label="顶部阈值" label-placement="left" :label-width="80">
                      <n-input-number :value="local.position_gate_top"
                        @update:value="(v: number) => local.position_gate_top = v"
                        :min="0.50" :max="0.99" :step="0.01" style="width: 90px;" />
                    </n-form-item>
                  </n-grid-item>
                </n-grid>
                <n-form-item label="DI差值跳过" label-placement="left" :label-width="110">
                  <n-input-number :value="local.di_gate_skip_threshold"
                    @update:value="(v: number) => local.di_gate_skip_threshold = v"
                    :min="5" :max="100" style="width: 110px;" />
                  <template #feedback>|+DI - -DI| 大于此值时跳过位置门禁（默认20，趋势市有效）</template>
                </n-form-item>
              </template>
            </n-card>

            <!-- 急跌急涨 -->
            <n-card size="small" :segmented="{ content: true }" style="margin-bottom: 8px;">
              <template #header>
                <n-space align="center" style="display: flex; justify-content: space-between;">
                  <span style="font-weight: 600;">② 急跌急涨惩罚</span>
                  <n-switch :value="local.rally_drop_enabled"
                    @update:value="(v: boolean) => local.rally_drop_enabled = v" />
                </n-space>
              </template>
              <template v-if="local.rally_drop_enabled">
                <n-form-item label="检测周期（K线）" label-placement="left" :label-width="110">
                  <n-input-number :value="local.rally_drop_lookback"
                    @update:value="(v: number) => local.rally_drop_lookback = v"
                    :min="5" :max="100" style="width: 110px;" />
                </n-form-item>
                <n-form-item label="阈值（%）" label-placement="left" :label-width="110">
                  <n-input-number :value="local.rally_drop_threshold"
                    @update:value="(v: number) => local.rally_drop_threshold = v"
                    :min="0.1" :max="5.0" :step="0.1" style="width: 110px;" />
                </n-form-item>
                <n-form-item label="ADX跳过" label-placement="left" :label-width="110">
                  <n-input-number :value="local.rally_drop_adx_skip"
                    @update:value="(v: number) => local.rally_drop_adx_skip = v"
                    :min="10" :max="60" style="width: 110px;" />
                  <template #feedback>ADX 大于此值时跳过急跌惩罚（默认25，趋势市不惩罚正常波动）</template>
                </n-form-item>
              </template>
            </n-card>

            <!-- 回撤止盈 -->
            <n-card size="small" :segmented="{ content: true }" style="margin-bottom: 8px;">
              <template #header>
                <n-space align="center" style="display: flex; justify-content: space-between;">
                  <span style="font-weight: 600;">③ 利润回撤止盈</span>
                  <n-switch :value="local.profit_drawdown_enabled"
                    @update:value="(v: boolean) => local.profit_drawdown_enabled = v" />
                </n-space>
              </template>
              <template v-if="local.profit_drawdown_enabled">
                <n-form-item label="回撤比例" label-placement="left" :label-width="110">
                  <n-input-number :value="local.profit_drawdown_pct"
                    @update:value="(v: number) => local.profit_drawdown_pct = v"
                    :min="0.05" :max="1.0" :step="0.05" style="width: 110px;" />
                </n-form-item>
                <n-form-item label="峰值门槛(ATR)" label-placement="left" :label-width="110">
                  <n-input-number :value="local.profit_drawdown_min_peak_atr"
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
      保存协调器配置
    </n-button>
  </n-space>
</template>
