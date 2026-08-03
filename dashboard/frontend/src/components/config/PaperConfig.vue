<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage, useDialog } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()
const dialog = useDialog()

function defaults() {
  const pt = store.items.paper_trading
  return {
    enabled: pt?.enabled ?? false,
    max_positions: pt?.max_positions ?? 10,
    ignore_gates: pt?.ignore_gates ?? true,
    initial_balance: pt?.initial_balance ?? 0,
  }
}

const local = reactive(defaults())

const original = computed(() => defaults())
const changed = computed(() => JSON.stringify(local) !== JSON.stringify(original.value))

watch(() => store.items, () => Object.assign(local, defaults()), { deep: true })

async function save() {
  await store.updatePaperConfig({ ...local })
  message.success('纸面配置已保存')
}

function confirmReset() {
  dialog.warning({
    title: '确认清空纸面数据',
    content: '清空 papertest_bridge.csv 和本地模拟持仓，此操作不可恢复，确定继续？',
    positiveText: '确定清空',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await store.resetPaperData()
        message.success('纸面数据已清空')
      } catch {
        message.error('清空纸面数据失败')
      }
    },
  })
}
</script>

<template>
  <n-grid :cols="2" :x-gap="24" :y-gap="12">
    <!-- 左列 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-divider title-position="left">{{ $t('config.paper.switch_title') }}</n-divider>
        <n-form-item :label="$t('config.paper.paper_mode')">
          <n-switch :value="local.enabled"
            @update:value="(v: any) => v != null && (local.enabled = v)" />
          <template #feedback>{{ $t('config.paper.paper_mode_feedback') }}</template>
        </n-form-item>

        <n-divider title-position="left">{{ $t('config.paper.position_limit') }}</n-divider>
        <n-form-item :label="$t('config.paper.max_positions')">
          <app-input-number :value="local.max_positions" :min="1" :max="50"
            @update:value="(v: any) => v != null && (local.max_positions = v)" style="width:100%;" />
          <template #feedback>{{ $t('config.paper.max_positions_feedback') }}</template>
        </n-form-item>

        <n-divider title-position="left">{{ $t('config.paper.virtual_balance') }}</n-divider>
        <n-form-item :label="$t('config.paper.initial_balance')">
          <app-input-number :value="local.initial_balance" :min="0" :max="100000"
            @update:value="(v: any) => v != null && (local.initial_balance = v)" style="width:100%;" />
          <template #feedback>{{ $t('config.paper.initial_balance_feedback') }}</template>
        </n-form-item>
      </n-space>
    </n-grid-item>

    <!-- 右列 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-divider title-position="left">{{ $t('config.paper.gate_control') }}</n-divider>
        <n-form-item :label="$t('config.paper.ignore_gates')">
          <n-switch :value="local.ignore_gates"
            @update:value="(v: any) => v != null && (local.ignore_gates = v)" />
          <template #feedback>{{ $t('config.paper.ignore_gates_feedback') }}</template>
        </n-form-item>

        <n-divider title-position="left">{{ $t('config.paper.risk_warning') }}</n-divider>
        <n-alert type="warning">
          {{ $t('config.paper.risk_warning_content') }}
        </n-alert>

        <n-divider title-position="left">{{ $t('config.paper.reset_title') }}</n-divider>
        <n-button type="warning" secondary block @click="confirmReset">
          {{ $t('config.paper.reset_button') }}
        </n-button>
        <n-text depth="3" style="font-size: 12px;">
          {{ $t('config.paper.reset_desc') }}
        </n-text>
      </n-space>
    </n-grid-item>
  </n-grid>

  <div style="margin-top: 16px;">
    <n-button type="primary" :disabled="!changed" @click="save" block>
      {{ $t('config.paper.save') }}
    </n-button>
  </div>
</template>
