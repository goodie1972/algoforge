<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage, useDialog } from 'naive-ui'
import { useI18n } from 'vue-i18n'

const store = useConfigStore()
const message = useMessage()
const dialog = useDialog()
const { t } = useI18n()

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
  message.success(t('config.saved'))
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
  <n-grid :cols="2" :x-gap="24" :y-gap="12">
    <!-- 左列 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-divider title-position="left">{{ $t('config.paper_enable') }}</n-divider>
        <n-form-item :label="$t('config.paper')">
          <n-switch :value="local.enabled"
            @update:value="(v: any) => v != null && (local.enabled = v)" />
          <template #feedback>{{ $t('config.paper_desc') }}</template>
        </n-form-item>

        <n-divider title-position="left">{{ $t('config.position_limit') }}</n-divider>
        <n-form-item label-placement="left" :label="$t('config.max_positions')">
          <app-input-number :value="local.max_positions" :min="1" :max="50"
            @update:value="(v: any) => v != null && (local.max_positions = v)" style="width: 30px;" />
          <template #feedback>{{ $t('config.max_positions_desc') }}</template>
        </n-form-item>

        <n-divider title-position="left">{{ $t('config.virtual_balance') }}</n-divider>
        <n-form-item label-placement="left" :label="$t('config.init_balance')">
          <app-input-number :value="local.initial_balance" :min="0" :max="100000"
            @update:value="(v: any) => v != null && (local.initial_balance = v)" style="width: 30px;" />
          <template #feedback>{{ $t('config.init_balance_desc') }}</template>
        </n-form-item>
      </n-space>
    </n-grid-item>

    <!-- 右列 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-divider title-position="left">{{ $t('config.gate_control') }}</n-divider>
        <n-form-item :label="$t('config.ignore_gates')">
          <n-switch :value="local.ignore_gates"
            @update:value="(v: any) => v != null && (local.ignore_gates = v)" />
          <template #feedback>{{ $t('config.ignore_gates_desc') }}</template>
        </n-form-item>

        <n-divider title-position="left">{{ $t('config.risk_note') }}</n-divider>
        <n-alert type="warning">
          {{ $t('config.risk_note_desc') }}
        </n-alert>

        <n-divider title-position="left">{{ $t('config.reset_paper') }}</n-divider>
        <n-button type="warning" secondary block @click="confirmReset">
          {{ $t('config.reset_paper_action') }}
        </n-button>
        <n-text depth="3" style="font-size: 12px;">
          {{ $t('config.reset_paper_desc') }}
        </n-text>
      </n-space>
    </n-grid-item>
  </n-grid>

  <div style="margin-top: 16px;">
    <n-button type="primary" :disabled="!changed" @click="save" block>
      {{ $t('config.save_paper') }}
    </n-button>
  </div>
</template>
