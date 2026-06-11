<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()

function defaults() {
  return {
    lot_size: store.items.lot_size ?? 0.01,
    max_positions: store.items.max_positions ?? 3,
    stop_loss_pips: store.items.stop_loss_pips ?? 50,
    take_profit_pips: store.items.take_profit_pips ?? 100,
    slippage: store.items.slippage ?? 30,
    profit_exit_cooldown_hours: store.items.profit_exit_cooldown_hours ?? 2,
    max_daily_loss_pct: store.items.max_daily_loss_pct ?? 12.0,
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
  message.success('风控配置已保存')
}
</script>

<template>
  <n-grid :cols="2" :x-gap="24" :y-gap="12">
    <!-- 左列：仓位 + 止损止盈 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-divider title-position="left">仓位管理</n-divider>
        <n-form-item label="每次开仓手数">
          <n-input-number :value="local.lot_size" :min="0.01" :max="10" :step="0.01"
            @update:value="(v: any) => v != null && (local.lot_size = v)" style="width:100%;" />
        </n-form-item>
        <n-form-item label="最大同时持仓数">
          <n-input-number :value="local.max_positions" :min="1" :max="20"
            @update:value="(v: any) => v != null && (local.max_positions = v)" style="width:100%;" />
        </n-form-item>

        <n-divider title-position="left">止损止盈</n-divider>
        <n-form-item label="默认止损 (点数)">
          <n-input-number :value="local.stop_loss_pips" :min="10" :max="500"
            @update:value="(v: any) => v != null && (local.stop_loss_pips = v)" style="width:100%;" />
        </n-form-item>
        <n-form-item label="默认止盈 (点数)">
          <n-input-number :value="local.take_profit_pips" :min="10" :max="1000"
            @update:value="(v: any) => v != null && (local.take_profit_pips = v)" style="width:100%;" />
        </n-form-item>
        <n-form-item label="允许滑点 (Points)">
          <n-input-number :value="local.slippage" :min="0" :max="100"
            @update:value="(v: any) => v !== null && (local.slippage = v)" style="width:100%;" />
        </n-form-item>
        <n-form-item label="止盈冷却时间 (小时)">
          <n-input-number :value="local.profit_exit_cooldown_hours" :min="0" :max="48" :step="0.5"
            @update:value="(v: any) => v !== null && (local.profit_exit_cooldown_hours = v)" style="width:100%;" />
          <template #feedback>盈利平仓后 N 小时内不再开同向单，0 为不限制</template>
        </n-form-item>
      </n-space>
    </n-grid-item>

    <!-- 右列：风控限制 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-divider title-position="left">账户级硬止损</n-divider>
        <n-form-item label="全局已实现亏损上限 (%)">
          <n-input-number :value="local.max_daily_loss_pct" :min="1" :max="100" :step="0.5"
            @update:value="(v: any) => v != null && (local.max_daily_loss_pct = v)" style="width:100%;" />
          <template #feedback>超过此比例后所有策略暂停开仓</template>
        </n-form-item>

        <n-divider title-position="left">浮动亏损 (单策略)</n-divider>
        <n-form-item label="警告线 (%)">
          <n-input-number :value="local.floating_loss_warn_pct" :min="1" :max="50" :step="0.5"
            @update:value="(v: any) => v != null && (local.floating_loss_warn_pct = v)" style="width:100%;" />
          <template #feedback>仅记录日志，不阻断</template>
        </n-form-item>
        <n-form-item label="阻断线 (%)">
          <n-input-number :value="local.floating_loss_block_pct" :min="1" :max="50" :step="0.5"
            @update:value="(v: any) => v != null && (local.floating_loss_block_pct = v)" style="width:100%;" />
          <template #feedback>浮动亏损超过此比例时暂停开仓，亏损降低后自动恢复</template>
        </n-form-item>

        <n-divider title-position="left">已实现亏损 (单策略)</n-divider>
        <n-form-item label="亏损上限 (%)">
          <n-input-number :value="local.per_strategy_realized_loss_pct" :min="1" :max="50" :step="0.5"
            @update:value="(v: any) => v != null && (local.per_strategy_realized_loss_pct = v)" style="width:100%;" />
          <template #feedback>单策略累计已实现亏损超过此比例时触发阻断</template>
        </n-form-item>
        <n-form-item label="阻断时长 (小时)">
          <n-input-number :value="local.per_strategy_loss_block_hours" :min="1" :max="72"
            @update:value="(v: any) => v != null && (local.per_strategy_loss_block_hours = v)" style="width:100%;" />
          <template #feedback>阻断到期后自动恢复，不影响其他策略</template>
        </n-form-item>

        <n-divider title-position="left">快速出场检测 (单策略)</n-divider>
        <n-form-item label="窗口内最大出场次数">
          <n-input-number :value="local.max_rapid_exits" :min="1" :max="20"
            @update:value="(v: any) => v != null && (local.max_rapid_exits = v)" style="width:100%;" />
        </n-form-item>
        <n-form-item label="检测窗口 (秒)">
          <n-input-number :value="local.rapid_exit_window_seconds" :min="60" :max="3600" :step="60"
            @update:value="(v: any) => v != null && (local.rapid_exit_window_seconds = v)" style="width:100%;" />
          <template #feedback>{{ Math.round(local.rapid_exit_window_seconds / 60) }} 分钟内出场超过上限则触发</template>
        </n-form-item>
        <n-form-item label="冷却时长 (秒)">
          <n-input-number :value="local.rapid_exit_cooldown_seconds" :min="300" :max="86400" :step="300"
            @update:value="(v: any) => v != null && (local.rapid_exit_cooldown_seconds = v)" style="width:100%;" />
          <template #feedback>触发后 {{ Math.round(local.rapid_exit_cooldown_seconds / 60) }} 分钟不能开单</template>
        </n-form-item>

        <n-divider title-position="left">单策略绝对亏损冷却</n-divider>
        <n-form-item label="已实现亏损上限 ($)">
          <n-input-number :value="local.per_strategy_realized_loss_amount" :min="5" :max="500" :step="5"
            @update:value="(v: any) => v != null && (local.per_strategy_realized_loss_amount = v)" style="width:100%;" />
          <template #feedback>单策略累计已实现亏损 ≥${{ local.per_strategy_realized_loss_amount }} 触发冷却</template>
        </n-form-item>

        <n-divider title-position="left">连续亏损冷却</n-divider>
        <n-form-item label="连续亏损上限 (次)">
          <n-input-number :value="local.max_consecutive_losses" :min="1" :max="20"
            @update:value="(v: any) => v != null && (local.max_consecutive_losses = v)" style="width:100%;" />
          <template #feedback>连续亏损达到此次数后触发冷却</template>
        </n-form-item>
        <n-form-item label="冷却时长 (小时)">
          <n-input-number :value="local.consecutive_loss_cooldown_hours" :min="1" :max="72"
            @update:value="(v: any) => v != null && (local.consecutive_loss_cooldown_hours = v)" style="width:100%;" />
          <template #feedback>冷却到期后自动恢复</template>
        </n-form-item>

        <n-divider title-position="left">安全锁</n-divider>
        <n-form-item label="锁自动过期 (分钟)">
          <n-input-number :value="local.safety_lock_timeout_minutes" :min="10" :max="1440" :step="5"
            @update:value="(v: any) => v != null && (local.safety_lock_timeout_minutes = v)" style="width:100%;" />
          <template #feedback>可疑场景触发安全锁后，超过此时长自动清除</template>
        </n-form-item>
      </n-space>
    </n-grid-item>
  </n-grid>

  <div style="margin-top: 16px;">
    <n-button type="primary" :disabled="!changed" @click="save" block>
      保存风控配置
    </n-button>
  </div>
</template>
