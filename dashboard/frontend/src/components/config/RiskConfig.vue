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
</script>

<template>
  <n-grid :cols="2" :x-gap="24" :y-gap="12">
    <!-- 左列 -->
    <n-grid-item>
      <n-grid :cols="3" :x-gap="12" :y-gap="12">
        <n-grid-item :span="3">
          <n-divider title-position="left">{{ $t('config.section.position_mgmt') }}</n-divider>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.lot_size')">
            <app-input-number :value="local.lot_size" :min="0.01" :max="10" :step="0.01"
              @update:value="(v: any) => v != null && (local.lot_size = v)" style="width: 30px;" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.max_positions_label')">
            <app-input-number :value="local.max_positions" :min="1" :max="20"
              @update:value="(v: any) => v != null && (local.max_positions = v)" style="width: 30px;" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.abs_loss_limit')">
            <app-input-number :value="local.per_strategy_realized_loss_amount" :min="5" :max="500" :step="5"
              @update:value="(v: any) => v != null && (local.per_strategy_realized_loss_amount = v)" style="width: 30px;" />
            <template #feedback>{{ $t('config.abs_loss_limit_desc') }}</template>
          </n-form-item>
        </n-grid-item>

        <n-grid-item :span="3">
          <n-divider title-position="left">{{ $t('config.account_sltp') }}</n-divider>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.default_sl')">
            <app-input-number :value="local.stop_loss_pips" :min="10" :max="500"
              @update:value="(v: any) => v != null && (local.stop_loss_pips = v)" style="width: 30px;" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.default_tp')">
            <app-input-number :value="local.take_profit_pips" :min="10" :max="1000"
              @update:value="(v: any) => v != null && (local.take_profit_pips = v)" style="width: 30px;" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.slippage')">
            <app-input-number :value="local.slippage" :min="0" :max="100"
              @update:value="(v: any) => v !== null && (local.slippage = v)" style="width: 30px;" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.tp_cooldown')">
            <app-input-number :value="local.profit_exit_cooldown_hours" :min="0" :max="48" :step="0.5"
              @update:value="(v: any) => v !== null && (local.profit_exit_cooldown_hours = v)" style="width: 30px;" />
            <template #feedback>{{ $t('config.tp_cooldown_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.safety_lock_expire')">
            <app-input-number :value="local.safety_lock_timeout_minutes" :min="10" :max="1440" :step="5"
              @update:value="(v: any) => v != null && (local.safety_lock_timeout_minutes = v)" style="width: 30px;" />
            <template #feedback>{{ $t('config.safety_lock_desc') }}</template>
          </n-form-item>
        </n-grid-item>
      </n-grid>
    </n-grid-item>

    <!-- 右列 -->
    <n-grid-item>
      <n-grid :cols="3" :x-gap="12" :y-gap="12">
        <n-grid-item :span="3">
          <n-divider title-position="left">{{ $t('config.section.floating_loss') }}</n-divider>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.warning_line')">
            <app-input-number :value="local.floating_loss_warn_pct" :min="1" :max="50" :step="0.5"
              @update:value="(v: any) => v != null && (local.floating_loss_warn_pct = v)" style="width: 30px;" />
            <template #feedback>{{ $t('config.warning_line_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.block_line')">
            <app-input-number :value="local.floating_loss_block_pct" :min="1" :max="50" :step="0.5"
              @update:value="(v: any) => v != null && (local.floating_loss_block_pct = v)" style="width: 30px;" />
            <template #feedback>{{ $t('config.block_line_desc') }}</template>
          </n-form-item>
        </n-grid-item>

        <n-grid-item :span="3">
          <n-divider title-position="left">{{ $t('config.section.realized_loss') }}</n-divider>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.realized_loss_pct')">
            <app-input-number :value="local.per_strategy_realized_loss_pct" :min="1" :max="50" :step="0.5"
              @update:value="(v: any) => v != null && (local.per_strategy_realized_loss_pct = v)" style="width: 30px;" />
            <template #feedback>{{ $t('config.realized_loss_pct_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.block_duration')">
            <app-input-number :value="local.per_strategy_loss_block_hours" :min="1" :max="72"
              @update:value="(v: any) => v != null && (local.per_strategy_loss_block_hours = v)" style="width: 30px;" />
            <template #feedback>{{ $t('config.block_duration_desc') }}</template>
          </n-form-item>
        </n-grid-item>

        <n-grid-item :span="3">
          <n-divider title-position="left">{{ $t('config.section.rapid_exit') }}</n-divider>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.max_rapid_exits')">
            <app-input-number :value="local.max_rapid_exits" :min="1" :max="20"
              @update:value="(v: any) => v != null && (local.max_rapid_exits = v)" style="width: 30px;" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.rapid_exit_window')">
            <app-input-number :value="local.rapid_exit_window_seconds" :min="60" :max="3600" :step="60"
              @update:value="(v: any) => v != null && (local.rapid_exit_window_seconds = v)" style="width: 30px;" />
            <template #feedback>{{ $t('config.rapid_exit_window_desc', { n: Math.round(local.rapid_exit_window_seconds / 60) }) }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.rapid_exit_cooldown')">
            <app-input-number :value="local.rapid_exit_cooldown_seconds" :min="300" :max="86400" :step="300"
              @update:value="(v: any) => v != null && (local.rapid_exit_cooldown_seconds = v)" style="width: 30px;" />
            <template #feedback>{{ $t('config.rapid_exit_cooldown_desc', { n: Math.round(local.rapid_exit_cooldown_seconds / 60) }) }}</template>
          </n-form-item>
        </n-grid-item>

        <n-grid-item :span="3">
          <n-divider title-position="left">{{ $t('config.consec_loss') }}</n-divider>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.consec_loss_limit')">
            <app-input-number :value="local.max_consecutive_losses" :min="1" :max="20"
              @update:value="(v: any) => v != null && (local.max_consecutive_losses = v)" style="width: 30px;" />
            <template #feedback>{{ $t('config.consec_loss_desc') }}</template>
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label-placement="left" :label="$t('config.consec_loss_cooldown')">
            <app-input-number :value="local.consecutive_loss_cooldown_hours" :min="1" :max="72"
              @update:value="(v: any) => v != null && (local.consecutive_loss_cooldown_hours = v)" style="width: 30px;" />
            <template #feedback>{{ $t('config.consec_loss_cooldown_desc') }}</template>
          </n-form-item>
        </n-grid-item>
      </n-grid>
    </n-grid-item>
  </n-grid>

  <div style="margin-top: 16px;">
    <n-button type="primary" :disabled="!changed" @click="save" block>
      {{ $t('config.save_risk') }}
    </n-button>
  </div>
</template>