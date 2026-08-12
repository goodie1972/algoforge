<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'

const store = useConfigStore()
const message = useMessage()
const { t } = useI18n()

function defaults() {
  return {
    lot_size: store.items.lot_size ?? 0.01,
    max_positions: store.items.max_positions ?? 3,
    stop_loss_pips: store.items.stop_loss_pips ?? 50,
    take_profit_pips: store.items.take_profit_pips ?? 100,
    slippage: store.items.slippage ?? 30,
    profit_exit_cooldown_hours: store.items.profit_exit_cooldown_hours ?? 2,
    floating_loss_warn_pct: store.items.floating_loss_warn_pct ?? 5.0,
    floating_loss_block_pct: store.items.floating_loss_block_pct ?? 10.0,
    per_strategy_realized_loss_pct: store.items.per_strategy_realized_loss_pct ?? 5.0,
    per_strategy_loss_block_hours: store.items.per_strategy_loss_block_hours ?? 12,
    max_rapid_exits: store.items.max_rapid_exits ?? 3,
    rapid_exit_window_seconds: store.items.rapid_exit_window_seconds ?? 300,
    rapid_exit_cooldown_seconds: store.items.rapid_exit_cooldown_seconds ?? 7200,
    per_strategy_realized_loss_amount: store.items.per_strategy_realized_loss_amount ?? 30.0,
    max_consecutive_losses: store.items.max_consecutive_losses ?? 3,
    consecutive_loss_cooldown_hours: store.items.consecutive_loss_cooldown_hours ?? 4,
    safety_lock_timeout_minutes: store.items.safety_lock_timeout_minutes ?? 90,
  }
}

const local = reactive(defaults())
const original = computed(() => defaults())
const changed = computed(() => JSON.stringify(local) !== JSON.stringify(original.value))

watch(() => store.items, () => Object.assign(local, defaults()), { deep: true })

async function save() {
  await store.update({ ...local })
  message.success(t('config.saved'))
}

// 下拉选项生成函数
function opts(values: number[]): { label: string; value: number }[] {
  return values.map(v => ({ label: String(v), value: v }))
}

// 离散参数下拉选项
const lotSizeOpts = opts([0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0])
const maxPosOpts = opts([1,2,3,4,5,6,7,8,9,10,12,15,20])
const slOpts = opts([10,20,30,40,50,60,70,80,90,100,120,150,200,300,500])
const tpOpts = opts([20,30,50,60,80,100,120,150,200,300,400,500,600,800,1000])
const slippageOpts = opts([0,1,2,3,4,5,6,7,8,9,10])
const cooldownOpts = opts([0,0.5,1,2,3,4,6,8,12,24,48])
const lossLimitOpts = opts([5,10,15,20,25,30,35,40,45,50,55,60,65,70,75,80,85,90,95,100])
const blockHrOpts = opts([1,2,3,4,6,8,12,16,24,36,48,72])
const rapidExitOpts = opts([1,2,3,4,5,6,8,10,15,20])
const rapidWinOpts = opts([60,120,180,300,600,900,1800,3600])
const rapidCoolOpts = opts([300,600,900,1800,2700,3600,5400,7200,10800,14400,21600,43200,86400])
const consecLossOpts = opts([1,2,3,4,5,6,8,10,15,20])
const consecCoolOpts = opts([1,2,3,4,6,8,12,16,24,36,48,72])
const safetyLockOpts = opts([10,15,30,45,60,90,120,180,240,360,480,720,1440])
const pctOpts = opts([1,2,3,4,5,6,7,8,9,10,12,15,20,25,30,40,50])
</script>

<template>
  <n-space vertical size="large">
    <!-- 卡片1: 仓位管理 -->
    <n-card size="small" :bordered="true">
      <template #header>
        <div style="display:flex;align-items:center;gap:6px;width:100%;">
          <span>{{ $t('config.section.position_mgmt') }}</span>
          <n-popover trigger="hover" placement="right">
            <template #trigger>
              <n-button text circle size="tiny" class="help-btn">?</n-button>
            </template>
            <div style="max-width:280px;font-size:12px;line-height:1.7;white-space:pre-line;">{{ $t('config.card_pos_mgmt_help') }}</div>
          </n-popover>
        </div>
      </template>
      <n-grid :cols="3" :x-gap="12" :y-gap="8">
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.lot_size')">
            <n-select :value="local.lot_size" :options="lotSizeOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.lot_size = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.lot_size_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.max_positions_label')">
            <n-select :value="local.max_positions" :options="maxPosOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.max_positions = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.max_positions_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.abs_loss_limit')">
            <n-select :value="local.per_strategy_realized_loss_amount" :options="lossLimitOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.per_strategy_realized_loss_amount = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.abs_loss_limit_desc') }}</template>
          </n-form-item>
        </n-grid-item>
      </n-grid>
    </n-card>

    <!-- 卡片2: 账户级止盈止损 -->
    <n-card size="small" :bordered="true">
      <template #header>
        <div style="display:flex;align-items:center;gap:6px;width:100%;">
          <span>{{ $t('config.account_sltp') }}</span>
          <n-popover trigger="hover" placement="right">
            <template #trigger>
              <n-button text circle size="tiny" class="help-btn">?</n-button>
            </template>
            <div style="max-width:280px;font-size:12px;line-height:1.7;white-space:pre-line;">{{ $t('config.card_sltp_help') }}</div>
          </n-popover>
        </div>
      </template>
      <n-grid :cols="3" :x-gap="12" :y-gap="8">
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.default_sl')">
            <n-select :value="local.stop_loss_pips" :options="slOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.stop_loss_pips = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.default_sl_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.default_tp')">
            <n-select :value="local.take_profit_pips" :options="tpOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.take_profit_pips = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.default_tp_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.slippage')">
            <n-select :value="local.slippage" :options="slippageOpts" size="tiny"
              @update:value="(v: any) => v !== null && (local.slippage = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.slippage_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.tp_cooldown')">
            <n-select :value="local.profit_exit_cooldown_hours" :options="cooldownOpts" size="tiny"
              @update:value="(v: any) => v !== null && (local.profit_exit_cooldown_hours = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.tp_cooldown_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.safety_lock_expire')">
            <n-select :value="local.safety_lock_timeout_minutes" :options="safetyLockOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.safety_lock_timeout_minutes = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.safety_lock_desc') }}</template>
          </n-form-item>
        </n-grid-item>
      </n-grid>
    </n-card>

    <!-- 卡片3: 单策略风控 -->
    <n-card size="small" :bordered="true">
      <template #header>
        <div style="display:flex;align-items:center;gap:6px;width:100%;">
          <span>{{ $t('config.section.risk_control') }}</span>
          <n-popover trigger="hover" placement="right">
            <template #trigger>
              <n-button text circle size="tiny" class="help-btn">?</n-button>
            </template>
            <div style="max-width:280px;font-size:12px;line-height:1.7;white-space:pre-line;">{{ $t('config.card_risk_help') }}</div>
          </n-popover>
        </div>
      </template>
      <n-grid :cols="3" :x-gap="12" :y-gap="8">
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.warning_line')">
            <n-select :value="local.floating_loss_warn_pct" :options="pctOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.floating_loss_warn_pct = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.warning_line_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.block_line')">
            <n-select :value="local.floating_loss_block_pct" :options="pctOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.floating_loss_block_pct = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.block_line_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.realized_loss_pct')">
            <n-select :value="local.per_strategy_realized_loss_pct" :options="pctOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.per_strategy_realized_loss_pct = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.realized_loss_pct_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.block_duration')">
            <n-select :value="local.per_strategy_loss_block_hours" :options="blockHrOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.per_strategy_loss_block_hours = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.block_duration_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.max_rapid_exits')">
            <n-select :value="local.max_rapid_exits" :options="rapidExitOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.max_rapid_exits = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.max_rapid_exits_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.rapid_exit_window')">
            <n-select :value="local.rapid_exit_window_seconds" :options="rapidWinOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.rapid_exit_window_seconds = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.rapid_exit_window_desc', { n: Math.round(local.rapid_exit_window_seconds / 60) }) }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.rapid_exit_cooldown')">
            <n-select :value="local.rapid_exit_cooldown_seconds" :options="rapidCoolOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.rapid_exit_cooldown_seconds = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.rapid_exit_cooldown_desc', { n: Math.round(local.rapid_exit_cooldown_seconds / 60) }) }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.consec_loss_limit')">
            <n-select :value="local.max_consecutive_losses" :options="consecLossOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.max_consecutive_losses = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.consec_loss_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.consec_loss_cooldown')">
            <n-select :value="local.consecutive_loss_cooldown_hours" :options="consecCoolOpts" size="tiny"
              @update:value="(v: any) => v != null && (local.consecutive_loss_cooldown_hours = v)" style="width: 80px;" />
            <template #feedback>{{ $t('config.consec_loss_cooldown_desc') }}</template>
          </n-form-item>
        </n-grid-item>
      </n-grid>
    </n-card>

    <div>
      <n-button type="primary" :disabled="!changed" @click="save" block>
        {{ $t('config.save_risk') }}
      </n-button>
    </div>
  </n-space>
</template>

<style scoped>
.help-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 1.5px solid #8b8f97;
  color: #8b8f97;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  background: transparent;
  line-height: 1;
  transition: border-color 0.2s, color 0.2s;
}
.help-btn:hover {
  border-color: #f0b90b;
  color: #f0b90b;
}
</style>