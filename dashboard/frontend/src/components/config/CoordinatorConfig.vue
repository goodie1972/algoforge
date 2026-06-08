<script setup lang="ts">
import { computed } from 'vue'
import { useConfigStore } from '@/stores/config'

const store = useConfigStore()

const cfg = computed(() => ({
  enabled: store.items?.coordinator?.enabled ?? false,
  // 功能①：跨策略联动
  cross_exit_enabled: store.items?.coordinator?.cross_exit_enabled ?? false,
  signal_strategy: store.items?.coordinator?.signal_strategy ?? 'H1_v6_hybrid',
  signal_direction: store.items?.coordinator?.signal_direction ?? 'BUY',
  target_strategies: store.items?.coordinator?.target_strategies ?? [],
  target_direction: store.items?.coordinator?.target_direction ?? 'SELL',
  // 功能②③：短周期反向止盈
  m15_reverse_tp_enabled: store.items?.coordinator?.m15_reverse_tp_enabled ?? false,
  m5_reverse_tp_enabled: store.items?.coordinator?.m5_reverse_tp_enabled ?? false,
}))

const strategyOptions = computed(() => {
  const pool = store.items?.strategy_pool || {}
  return Object.keys(pool).map(name => ({
    label: name,
    value: name,
  }))
})

const directionOptions = [
  { label: '做多 (BUY)', value: 'BUY' },
  { label: '做空 (SELL)', value: 'SELL' },
]

async function update(key: string, value: any) {
  const current = { ...cfg.value, [key]: value }
  await store.updateCoordinator(current)
}
</script>

<template>
  <n-grid :cols="2" :x-gap="24" :y-gap="12">
    <!-- 左列 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-form-item label="启用协调器">
          <n-switch :value="cfg.enabled"
            @update:value="(v: boolean) => update('enabled', v)" />
          <template #feedback>
            开启后可按需启用下方功能
          </template>
        </n-form-item>

        <template v-if="cfg.enabled">
          <n-divider title-position="left">功能①：跨策略联动出场</n-divider>

          <n-form-item label="启用联动出场">
            <n-switch :value="cfg.cross_exit_enabled"
              @update:value="(v: boolean) => update('cross_exit_enabled', v)" />
            <template #feedback>信号策略盈利时，联动关闭目标策略的对应方向盈利单</template>
          </n-form-item>

          <template v-if="cfg.cross_exit_enabled">
            <n-form-item label="信号策略">
              <n-select :value="cfg.signal_strategy" :options="strategyOptions"
                @update:value="(v: string) => update('signal_strategy', v)"
                style="width: 100%;" />
            </n-form-item>

            <n-form-item label="信号方向">
              <n-select :value="cfg.signal_direction" :options="directionOptions"
                @update:value="(v: string) => update('signal_direction', v)"
                style="width: 100%;" />
              <template #feedback>该方向的持仓盈利时触发联动</template>
            </n-form-item>
          </template>
        </template>
      </n-space>
    </n-grid-item>

    <!-- 右列 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <template v-if="cfg.enabled">
          <n-divider title-position="left">功能②③：短周期反向止盈</n-divider>

          <n-form-item label="M15 反向止盈">
            <n-switch :value="cfg.m15_reverse_tp_enabled"
              @update:value="(v: boolean) => update('m15_reverse_tp_enabled', v)" />
            <template #feedback>M15 EMA20 斜率转势时平盈利单，比 M30 早 15-30 分钟反应</template>
          </n-form-item>

          <n-form-item label="M5 反向止盈">
            <n-switch :value="cfg.m5_reverse_tp_enabled"
              @update:value="(v: boolean) => update('m5_reverse_tp_enabled', v)" />
            <template #feedback>M5 EMA20 斜率转势时平盈利单，反应最快但可能误触</template>
          </n-form-item>

          <template v-if="cfg.cross_exit_enabled">
            <n-divider title-position="left">联动目标设置</n-divider>

            <n-form-item label="受影响策略">
              <n-checkbox-group :value="cfg.target_strategies"
                @update:value="(v: string[]) => update('target_strategies', v)">
                <n-space vertical size="small">
                  <n-checkbox v-for="opt in strategyOptions" :key="opt.value"
                    :value="opt.value" :label="opt.label" />
                </n-space>
              </n-checkbox-group>
              <template #feedback>勾选需要被联动平仓的策略</template>
            </n-form-item>

            <n-form-item label="目标方向">
              <n-select :value="cfg.target_direction" :options="directionOptions"
                @update:value="(v: string) => update('target_direction', v)"
                style="width: 100%;" />
              <template #feedback>关闭目标策略的哪个方向</template>
            </n-form-item>
          </template>

          <n-divider title-position="left">规则说明</n-divider>

          <n-alert type="info" :bordered="false" style="font-size: 13px;">
            <div v-if="cfg.cross_exit_enabled">
              当 <n-text code>{{ cfg.signal_strategy }}</n-text> 的
              <n-text code>{{ cfg.signal_direction === 'BUY' ? '多单' : '空单' }}</n-text>
              盈利时，自动关闭
              <n-text code>{{ cfg.target_strategies.join('、') || '(未选择)' }}</n-text>
              的
              <n-text code>{{ cfg.target_direction === 'SELL' ? '空单' : '多单' }}</n-text>
              盈利单。
            </div>
            <div v-if="cfg.m15_reverse_tp_enabled || cfg.m5_reverse_tp_enabled">
              当
              <template v-if="cfg.m15_reverse_tp_enabled"><n-text code>M15</n-text></template>
              <template v-if="cfg.m15_reverse_tp_enabled && cfg.m5_reverse_tp_enabled"> / </template>
              <template v-if="cfg.m5_reverse_tp_enabled"><n-text code>M5</n-text></template>
              EMA20 斜率反向时，平掉所有同向盈利单。
            </div>
            <div v-if="!cfg.cross_exit_enabled && !cfg.m15_reverse_tp_enabled && !cfg.m5_reverse_tp_enabled">
              请勾选上方功能后启用
            </div>
          </n-alert>
        </template>
      </n-space>
    </n-grid-item>
  </n-grid>
</template>
