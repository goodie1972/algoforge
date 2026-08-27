<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useConfigStore } from '@/stores/config'
import { restartEngine } from '@/api/client'
import { useMessage, useDialog } from 'naive-ui'
import { useI18n } from 'vue-i18n'

const store = useConfigStore()
const message = useMessage()
const dialog = useDialog()
const { t } = useI18n()

// 持仓数下拉选项
const maxPosOpts = [1,2,3,4,5,6,7,8,9,10,12,15,20,25,30,40,50].map(v => ({ label: String(v), value: v }))
// 手数下拉选项
const lotSizeOpts = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0].map(v => ({ label: String(v), value: v }))

function defaults() {
  const pt = store.items.paper_trading
  return {
    enabled: pt?.enabled ?? false,
    // 兜底值 10 与后端 core/runtime_config.py 的 PAPER_DEFAULT_MAX_POSITIONS 保持一致
    max_positions: pt?.max_positions ?? 10,
    ignore_gates: pt?.ignore_gates ?? true,
    initial_balance: pt?.initial_balance ?? 0,
    lot_size: pt?.lot_size ?? 0.01,
    total_max_positions: pt?.total_max_positions ?? 0,
  }
}

const local = reactive(defaults())

const original = computed(() => defaults())
const changed = computed(() => JSON.stringify(local) !== JSON.stringify(original.value))

watch(() => store.items, () => Object.assign(local, defaults()), { deep: true })

async function save() {
  try {
    const res = await store.updatePaperConfig({ ...local })
    message.success(t('config.saved'))
    if (res?.mode_switch) confirmRestart()
  } catch {
    message.error(t('common.failed'))
  }
}

// 模式切换确认：配置已保存但未自动重启，由用户决定是否立即重启引擎
function confirmRestart() {
  dialog.warning({
    title: t('config.mode_switch_title'),
    content: t('config.mode_switch_content'),
    positiveText: t('config.mode_switch_yes'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        const res = await restartEngine()
        message.success(t('config.restart_done', { status: res?.status || '' }))
      } catch {
        message.error(t('config.restart_fail'))
      }
    },
    onNegativeClick: () => {
      message.info(t('config.mode_switch_manual'))
    },
  })
}

function confirmReset() {
  dialog.warning({
    title: t('config.reset_paper'),
    content: t('config.reset_paper_desc'),
    positiveText: t('config.reset_paper_action'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await store.resetPaperData()
        message.success(t('config.reset_done'))
      } catch {
        message.error(t('common.failed'))
      }
    },
  })
}
</script>

<template>
  <n-space vertical size="large">
    <n-grid :cols="2" :x-gap="24">
      <!-- 左列 -->
      <n-grid-item>
        <n-space vertical size="medium">
          <!-- 卡片1: 纸面交易 -->
          <n-card size="small" :bordered="true">
            <template #header>
              <div style="display:flex;align-items:center;gap:6px;width:100%;">
                <span>{{ $t('config.paper_enable') }}</span>
                <n-popover trigger="hover" placement="right">
                  <template #trigger><n-button text circle size="tiny" filterable tag class="help-btn">?</n-button></template>
                  <div style="max-width:280px;font-size:12px;line-height:1.7;white-space:pre-line;">{{ $t('config.card_paper_enable_help') }}</div>
                </n-popover>
              </div>
            </template>
            <n-form-item :label="$t('config.paper')">
              <n-switch :value="local.enabled" @update:value="(v: any) => v != null && (local.enabled = v)" />
              <template #feedback>{{ $t('config.paper_desc') }}</template>
            </n-form-item>
          </n-card>

          <!-- 卡片2: 交易设置 -->
          <n-card size="small" :bordered="true">
            <template #header>
              <div style="display:flex;align-items:center;gap:6px;width:100%;">
                <span>{{ $t('config.trade_settings') }}</span>
                <n-popover trigger="hover" placement="right">
                  <template #trigger><n-button text circle size="tiny" filterable tag class="help-btn">?</n-button></template>
                  <div style="max-width:280px;font-size:12px;line-height:1.7;white-space:pre-line;">{{ $t('config.card_paper_trade_help') }}</div>
                </n-popover>
              </div>
            </template>
            <!-- 持仓数 + 余额 同一行 -->
            <n-grid :cols="2" :x-gap="12">
              <n-grid-item>
                <n-form-item label-placement="top" :label="$t('config.max_positions')">
                  <n-select :value="local.max_positions" :options="maxPosOpts" size="tiny" filterable tag
                    @update:value="(v: any) => v != null && (local.max_positions = v)" style="width: 110px;" />
                </n-form-item>
                <n-text depth="3" style="font-size:11px;">{{ $t('config.max_positions_desc') }}</n-text>
              </n-grid-item>
              <n-grid-item>
                <n-form-item label-placement="top" :label="$t('config.init_balance')">
                  <n-input-number :value="local.initial_balance" :min="0" :max="100000" :step="100" size="tiny" filterable tag
                    @update:value="(v: any) => v != null && (local.initial_balance = v)" style="width: 110px;" />
                </n-form-item>
                <n-text depth="3" style="font-size:11px;">{{ $t('config.init_balance_desc') }}</n-text>
              </n-grid-item>
            </n-grid>
            <!-- 手数 + 总持仓上限 同一行 -->
            <n-grid :cols="2" :x-gap="12">
              <n-grid-item>
                <n-form-item label-placement="top" :label="$t('config.paper_lot_size')">
                  <n-select :value="local.lot_size" :options="lotSizeOpts" size="tiny" filterable tag
                    @update:value="(v: any) => v != null && (local.lot_size = v)" style="width: 110px;" />
                </n-form-item>
                <n-text depth="3" style="font-size:11px;">{{ $t('config.paper_lot_size_desc') }}</n-text>
              </n-grid-item>
              <n-grid-item>
                <n-form-item label-placement="top" :label="$t('config.total_max_positions')">
                  <n-input-number :value="local.total_max_positions" :min="0" :max="1000" :step="1" size="tiny" filterable tag
                    @update:value="(v: any) => v != null && (local.total_max_positions = v)" style="width: 110px;" />
                </n-form-item>
                <n-text depth="3" style="font-size:11px;">{{ $t('config.total_max_positions_desc') }}</n-text>
              </n-grid-item>
            </n-grid>
          </n-card>

          <!-- 门禁控制 -->
          <n-card size="small" :bordered="true" :title="$t('config.gate_control')">
            <n-form-item :label="$t('config.ignore_gates')">
              <n-switch :value="local.ignore_gates" @update:value="(v: any) => v != null && (local.ignore_gates = v)" />
              <template #feedback>{{ $t('config.ignore_gates_desc') }}</template>
            </n-form-item>
          </n-card>
        </n-space>
      </n-grid-item>

      <!-- 右列 -->
      <n-grid-item>
        <n-space vertical size="medium">
          <!-- 风险提示 -->
          <n-card size="small" :bordered="true" :title="$t('config.risk_note')">
            <n-alert type="warning">{{ $t('config.risk_note_desc') }}</n-alert>
          </n-card>

          <!-- 重置纸面数据 -->
          <n-card size="small" :bordered="true" :title="$t('config.reset_paper')">
            <n-button type="warning" secondary block @click="confirmReset">
              {{ $t('config.reset_paper_action') }}
            </n-button>
            <n-text depth="3" style="font-size:12px;display:block;margin-top:8px;">
              {{ $t('config.reset_paper_desc') }}
            </n-text>
          </n-card>
        </n-space>
      </n-grid-item>
    </n-grid>

    <n-button type="primary" :disabled="!changed" @click="save" block>
      {{ $t('config.save_paper') }}
    </n-button>
  </n-space>
</template>

<style scoped>
.help-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 50%;
  border: 1.5px solid #8b8f97; color: #8b8f97;
  font-size: 11px; font-weight: 700; cursor: pointer;
  background: transparent; line-height: 1;
  transition: border-color 0.2s, color 0.2s;
}
.help-btn:hover { border-color: #f0b90b; color: #f0b90b; }
</style>
