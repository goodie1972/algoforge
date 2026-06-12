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
    cross_exit_enabled: store.items?.coordinator?.cross_exit_enabled ?? false,
    signal_strategy: store.items?.coordinator?.signal_strategy ?? 'H1_v6_hybrid',
    signal_direction: store.items?.coordinator?.signal_direction ?? 'BUY',
    target_strategies: store.items?.coordinator?.target_strategies ?? [],
    target_direction: store.items?.coordinator?.target_direction ?? 'SELL',
    m15_reverse_tp_enabled: store.items?.coordinator?.m15_reverse_tp_enabled ?? false,
    m15_reverse_tp_sensitivity: store.items?.coordinator?.m15_reverse_tp_sensitivity ?? 0.5,
  }
}

const local = reactive(defaults())

const original = computed(() => defaults())
const changed = computed(() => JSON.stringify({
  ...local,
  target_strategies: [...local.target_strategies].sort(),
}) !== JSON.stringify({
  ...original.value,
  target_strategies: [...original.value.target_strategies].sort(),
}))

watch(() => store.items?.coordinator, () => Object.assign(local, defaults()), { deep: true })

async function save() {
  await store.updateCoordinator({ ...local })
  message.success('协调器配置已保存')
}

const strategyOptions = computed(() => {
  const pool = store.items?.strategy_pool || {}
  return Object.keys(pool).map(name => ({ label: name, value: name }))
})

const directionOptions = [
  { label: '做多 (BUY)', value: 'BUY' },
  { label: '做空 (SELL)', value: 'SELL' },
]
</script>

<template>
  <n-space vertical size="medium">
    <n-grid :cols="2" :x-gap="24" :y-gap="12">
      <!-- 左列：启用开关 + 联动目标 + 规则说明 -->
      <n-grid-item>
        <n-space vertical size="medium">
          <n-form-item label="启用协调器">
            <n-switch :value="local.enabled"
              @update:value="(v: boolean) => local.enabled = v" />
            <template #feedback>开启后可按需启用右侧功能</template>
          </n-form-item>

          <template v-if="local.enabled">
            <n-divider title-position="left">联动目标设置</n-divider>

            <n-form-item label="受影响策略">
              <n-checkbox-group :value="local.target_strategies"
                @update:value="(v: string[]) => local.target_strategies = v">
                <n-space vertical size="small">
                  <n-checkbox v-for="opt in strategyOptions" :key="opt.value"
                    :value="opt.value" :label="opt.label" />
                </n-space>
              </n-checkbox-group>
              <template #feedback>勾选需要被联动平仓的策略</template>
            </n-form-item>

            <n-form-item label="目标方向">
              <n-select :value="local.target_direction" :options="directionOptions"
                @update:value="(v: string) => local.target_direction = v"
                style="width: 100%;" />
              <template #feedback>关闭目标策略的哪个方向</template>
            </n-form-item>

            <n-divider title-position="left">规则说明</n-divider>

            <n-alert type="info" :bordered="false" style="font-size: 13px;">
              <div v-if="local.cross_exit_enabled">
                当 <n-text code>{{ local.signal_strategy }}</n-text> 的
                <n-text code>{{ local.signal_direction === 'BUY' ? '多单' : '空单' }}</n-text>
                盈利时，自动关闭
                <n-text code>{{ local.target_strategies.join('、') || '(未选择)' }}</n-text>
                的
                <n-text code>{{ local.target_direction === 'SELL' ? '空单' : '多单' }}</n-text>
                盈利单。
              </div>
              <div v-if="local.m15_reverse_tp_enabled">
                当 <n-text code>M15</n-text> EMA20 斜率超过归一化阈值时，平掉所有原方向盈利单。
              </div>
              <div v-if="!local.cross_exit_enabled && !local.m15_reverse_tp_enabled">
                请勾选右侧功能后启用
              </div>
            </n-alert>
          </template>
        </n-space>
      </n-grid-item>

      <!-- 右列：功能① + 功能② -->
      <n-grid-item>
        <n-space vertical size="medium">
          <template v-if="local.enabled">
            <n-divider title-position="left">功能①：跨策略联动出场</n-divider>

            <n-form-item label="启用联动出场">
              <n-switch :value="local.cross_exit_enabled"
                @update:value="(v: boolean) => local.cross_exit_enabled = v" />
              <template #feedback>信号策略盈利时，联动关闭目标策略的对应方向盈利单</template>
            </n-form-item>

            <template v-if="local.cross_exit_enabled">
              <n-form-item label="信号策略">
                <n-select :value="local.signal_strategy" :options="strategyOptions"
                  @update:value="(v: string) => local.signal_strategy = v"
                  style="width: 100%;" />
              </n-form-item>

              <n-form-item label="信号方向">
                <n-select :value="local.signal_direction" :options="directionOptions"
                  @update:value="(v: string) => local.signal_direction = v"
                  style="width: 100%;" />
                <template #feedback>该方向的持仓盈利时触发联动</template>
              </n-form-item>
            </template>

            <n-divider title-position="left">功能②：M15 反向止盈</n-divider>

            <n-form-item label="M15 反向止盈">
              <n-switch :value="local.m15_reverse_tp_enabled"
                @update:value="(v: boolean) => local.m15_reverse_tp_enabled = v" />
              <template #feedback>M15 EMA20 斜率归一化反转时平盈利单（M5 过于敏感已移除）</template>
            </n-form-item>

            <template v-if="local.m15_reverse_tp_enabled">
              <n-form-item label="M15 灵敏度">
                <n-select :value="local.m15_reverse_tp_sensitivity"
                  :options="sensitivityOptions"
                  @update:value="(v: number) => local.m15_reverse_tp_sensitivity = v"
                  style="width: 100%;" />
                <template #feedback>斜率 / ATR ≥ 此值时触发，0.5=推荐 0=原版敏感逻辑</template>
              </n-form-item>
            </template>
          </template>
        </n-space>
      </n-grid-item>
    </n-grid>

    <n-button type="primary" :disabled="!changed" @click="save" block>
      保存协调器配置
    </n-button>
  </n-space>
</template>
