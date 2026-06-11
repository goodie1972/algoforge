<script setup lang="ts">
import { computed, ref, reactive, onMounted, watch } from 'vue'
import { useConfigStore } from '@/stores/config'
import { getNewsCalendar } from '@/api/client'
import { useMessage } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()

const local = reactive({
  news_filter_enabled: store.items.news_filter_enabled ?? true,
  news_before_minutes: store.items.news_before_minutes ?? 30,
  news_after_minutes: store.items.news_after_minutes ?? 30,
  news_impact_filter: store.items.news_impact_filter ?? 'High',
  news_currency_filter: store.items.news_currency_filter ?? 'USD',
})

const original = computed(() => ({
  news_filter_enabled: store.items.news_filter_enabled ?? true,
  news_before_minutes: store.items.news_before_minutes ?? 30,
  news_after_minutes: store.items.news_after_minutes ?? 30,
  news_impact_filter: store.items.news_impact_filter ?? 'High',
  news_currency_filter: store.items.news_currency_filter ?? 'USD',
}))

const changed = computed(() => JSON.stringify(local) !== JSON.stringify(original.value))

// 同步外部 store 变化到本地（如其他组件修改时）
watch(() => store.items, () => {
  Object.assign(local, {
    news_filter_enabled: store.items.news_filter_enabled ?? true,
    news_before_minutes: store.items.news_before_minutes ?? 30,
    news_after_minutes: store.items.news_after_minutes ?? 30,
    news_impact_filter: store.items.news_impact_filter ?? 'High',
    news_currency_filter: store.items.news_currency_filter ?? 'USD',
  })
}, { deep: true })

async function save() {
  await store.update({ ...local })
  message.success('新闻配置已保存')
}

const calendar = ref<any>(null)
const loading = ref(false)

async function refreshCalendar() {
  loading.value = true
  try {
    calendar.value = await getNewsCalendar()
  } catch {
    calendar.value = null
  } finally {
    loading.value = false
  }
}

onMounted(() => refreshCalendar())

const impactOptions = [
  { label: '仅 High', value: 'High' },
  { label: 'High + Medium', value: 'High,Medium' },
]
</script>

<template>
  <n-grid :cols="2" :x-gap="24" :y-gap="12">
    <!-- 左列：启用 + 禁售窗口 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-form-item label="启用新闻过滤">
          <n-switch :value="local.news_filter_enabled"
            @update:value="(v: boolean) => local.news_filter_enabled = v" />
        </n-form-item>

        <n-divider title-position="left">禁售时间窗口</n-divider>

        <n-form-item label="发布前 (分钟)">
          <n-input-number :value="local.news_before_minutes" :min="0" :max="999"
            @update:value="(v: any) => v !== null && (local.news_before_minutes = v)"
            style="width:100%;" />
          <template #feedback>数据发布前 N 分钟停止开新仓</template>
        </n-form-item>

        <n-form-item label="发布后 (分钟)">
          <n-input-number :value="local.news_after_minutes" :min="0" :max="999"
            @update:value="(v: any) => v !== null && (local.news_after_minutes = v)"
            style="width:100%;" />
          <template #feedback>数据发布后 N 分钟恢复交易</template>
        </n-form-item>

        <n-button type="primary" :disabled="!changed" @click="save" block>
          保存新闻配置
        </n-button>
      </n-space>
    </n-grid-item>

    <!-- 右列：筛选 + 状态 + 事件 -->
    <n-grid-item>
      <n-space vertical size="medium">
        <n-divider title-position="left">事件筛选</n-divider>

        <n-form-item label="影响级别">
          <n-select :value="local.news_impact_filter" :options="impactOptions"
            @update:value="(v: string) => local.news_impact_filter = v" />
        </n-form-item>

        <n-form-item label="关注货币">
          <n-input :value="local.news_currency_filter"
            @update:value="(v: string) => local.news_currency_filter = v"
            style="width:100%;" />
          <template #feedback>默认 USD，多个用逗号分隔</template>
        </n-form-item>

        <n-divider title-position="left">当前状态</n-divider>

        <n-alert v-if="calendar?.is_blackout" type="warning" :bordered="false">
          当前处于禁售期: {{ calendar.blackout_reason }}
        </n-alert>
        <n-alert v-else type="success" :bordered="false">
          当前无禁售，正常交易中
        </n-alert>

        <n-text depth="2" style="font-size: 13px;">本周高影响事件</n-text>
        <n-spin v-if="loading" size="small" />

        <n-empty v-else-if="!calendar || !calendar.upcoming_events?.length"
          description="本周无高影响事件" size="small" />

        <div v-else v-for="evt in calendar.upcoming_events.slice(0, 10)" :key="evt.datetime + evt.title"
          style="display: flex; align-items: center; justify-content: space-between;
            padding: 6px 8px; margin-bottom: 4px; border-radius: 4px;
            background: var(--n-color-embedded); font-size: 13px;">
          <div style="flex: 1;">
            <n-text>{{ evt.title }}</n-text>
            <n-text depth="3" style="margin-left: 6px;">{{ evt.country }}</n-text>
          </div>
          <div style="text-align: right;">
            <n-tag :type="evt.impact === 'High' ? 'error' : 'warning'" size="tiny">
              {{ evt.impact }}
            </n-tag>
            <n-text depth="3" style="margin-left: 6px; font-size: 11px;">
              {{ evt.datetime }}
            </n-text>
          </div>
        </div>

        <n-button @click="refreshCalendar" size="small" secondary>
          刷新事件列表
        </n-button>
      </n-space>
    </n-grid-item>
  </n-grid>
</template>
