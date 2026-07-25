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
        <n-divider title-position="left">纸面模式开关</n-divider>
        <n-form-item label="纸面模式">
          <n-switch :value="local.enabled"
            @update:value="(v: any) => v != null && (local.enabled = v)" />
          <template #feedback>开启后所有交易通过 PaperBridge 本地模拟，不影响真实 MT4 账户</template>
        </n-form-item>

        <n-divider title-position="left">持仓限制</n-divider>
        <n-form-item label="最大同时持仓数">
          <app-input-number :value="local.max_positions" :min="1" :max="50"
            @update:value="(v: any) => v != null && (local.max_positions = v)" style="width:100%;" />
          <template #feedback>纸面模式下单策略最大同时持仓数</template>
        </n-form-item>

        <n-divider title-position="left">虚拟余额</n-divider>
        <n-form-item label="初始虚拟余额 ($)">
          <app-input-number :value="local.initial_balance" :min="0" :max="100000"
            @update:value="(v: any) => v != null && (local.initial_balance = v)" style="width:100%;" />
          <template #feedback>0=从真实桥接获取余额，&gt;0=使用指定虚拟余额</template>
        </n-form-item>
      </n-space>
    </n-grid-item>

    <!-- 右列 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-divider title-position="left">门禁控制</n-divider>
        <n-form-item label="忽略门禁">
          <n-switch :value="local.ignore_gates"
            @update:value="(v: any) => v != null && (local.ignore_gates = v)" />
          <template #feedback>开启后忽略所有门禁（位置门禁、急跌急涨、利润回撤保护等），仅在纸面模式生效</template>
        </n-form-item>

        <n-divider title-position="left">风险提示</n-divider>
        <n-alert type="warning">
          纸面模式仅供策略验证使用。切换为实盘前请关闭纸面模式并重启引擎。
        </n-alert>

        <n-divider title-position="left">重置纸面数据</n-divider>
        <n-button type="warning" secondary block @click="confirmReset">
          清空纸面成交记录
        </n-button>
        <n-text depth="3" style="font-size: 12px;">
          清空 papertest_bridge.csv 和本地模拟持仓，不可恢复
        </n-text>
      </n-space>
    </n-grid-item>
  </n-grid>

  <div style="margin-top: 16px;">
    <n-button type="primary" :disabled="!changed" @click="save" block>
      保存纸面配置
    </n-button>
  </div>
</template>
