<script setup lang="ts">
import { computed, ref, reactive, onMounted, watch } from 'vue'
import { useConfigStore } from '@/stores/config'
import { getNewsCalendar } from '@/api/client'
import { useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import BiasStateIndicator from './BiasStateIndicator.vue'

const store = useConfigStore()
const message = useMessage()
const { t } = useI18n()

const local = reactive({
  news_filter_enabled: store.items.news_filter_enabled ?? true,
  news_before_minutes: store.items.news_before_minutes ?? 30,
  news_after_minutes: store.items.news_after_minutes ?? 30,
  news_impact_filter: store.items.news_impact_filter ?? 'High',
  news_currency_filter: store.items.news_currency_filter ?? 'USD',
  news_bias_enabled: store.items.news_bias_enabled ?? true,
  news_bias_report_hours: store.items.news_bias_report_hours ?? '0,12',
  block_long_when_bias_bearish: store.items.block_long_when_bias_bearish ?? false,
  block_short_when_bias_bullish: store.items.block_short_when_bias_bullish ?? false,
  news_bias_di_gap: store.items?.coordinator?.news_bias_di_gap ?? 8,
})

const original = computed(() => ({
  news_filter_enabled: store.items.news_filter_enabled ?? true,
  news_before_minutes: store.items.news_before_minutes ?? 30,
  news_after_minutes: store.items.news_after_minutes ?? 30,
  news_impact_filter: store.items.news_impact_filter ?? 'High',
  news_currency_filter: store.items.news_currency_filter ?? 'USD',
  news_bias_enabled: store.items.news_bias_enabled ?? true,
  news_bias_report_hours: store.items.news_bias_report_hours ?? '0,12',
  block_long_when_bias_bearish: store.items.block_long_when_bias_bearish ?? false,
  block_short_when_bias_bullish: store.items.block_short_when_bias_bullish ?? false,
  news_bias_di_gap: store.items?.coordinator?.news_bias_di_gap ?? 8,
}))

const changed = computed(() => JSON.stringify(local) !== JSON.stringify(original.value))

watch(() => store.items, () => {
  Object.assign(local, {
    news_filter_enabled: store.items.news_filter_enabled ?? true,
    news_before_minutes: store.items.news_before_minutes ?? 30,
    news_after_minutes: store.items.news_after_minutes ?? 30,
    news_impact_filter: store.items.news_impact_filter ?? 'High',
    news_currency_filter: store.items.news_currency_filter ?? 'USD',
    news_bias_enabled: store.items.news_bias_enabled ?? true,
    news_bias_report_hours: store.items.news_bias_report_hours ?? '0,12',
    block_long_when_bias_bearish: store.items.block_long_when_bias_bearish ?? false,
    block_short_when_bias_bullish: store.items.block_short_when_bias_bullish ?? false,
    news_bias_di_gap: store.items?.coordinator?.news_bias_di_gap ?? 8,
  })
}, { deep: true })

async function save() {
  const { news_bias_di_gap, ...general } = local
  await store.update(general)
  await store.updateCoordinator({ news_bias_di_gap })
  message.success(t('config.saved'))
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

onMounted(refreshCalendar)

const impactOptions = [
  { label: t('config.impact_high_only'), value: 'High' },
  { label: t('config.impact_high_medium'), value: 'High,Medium' },
]
</script>

<template>
  <n-grid :cols="2" :x-gap="24" :y-gap="12">
    <n-grid-item>
      <n-space vertical size="medium">
        <n-form-item :label="$t('config.news_filter_enable')">
          <n-switch :value="local.news_filter_enabled"
            @update:value="(v: boolean) => local.news_filter_enabled = v" />
        </n-form-item>

        <n-divider title-position="left">{{ $t('config.blackout_window') }}</n-divider>

        <div style="display: flex; gap: 24px;">
          <n-form-item label-placement="left" :label="$t('config.before_release')" style="flex: 1;">
            <app-input-number :value="local.news_before_minutes" :min="0" :max="999"
              @update:value="(v: any) => v !== null && (local.news_before_minutes = v)"
              style="width: 30px;" />
            <template #feedback>{{ $t('config.before_release_desc') }}</template>
          </n-form-item>
          <n-form-item label-placement="left" :label="$t('config.after_release')" style="flex: 1;">
            <app-input-number :value="local.news_after_minutes" :min="0" :max="999"
              @update:value="(v: any) => v !== null && (local.news_after_minutes = v)"
              style="width: 30px;" />
            <template #feedback>{{ $t('config.after_release_desc') }}</template>
          </n-form-item>
        </div>

        <n-divider title-position="left">{{ $t('config.news_bias') }}</n-divider>

        <n-form-item :label="$t('config.news_bias_enable')">
          <n-switch :value="local.news_bias_enabled"
            @update:value="(v: boolean) => local.news_bias_enabled = v" />
          <template #feedback>{{ $t('config.news_bias_desc') }}</template>
        </n-form-item>

        <n-form-item :label="$t('config.report_time_utc')">
          <n-input :value="local.news_bias_report_hours"
            @update:value="(v: string) => local.news_bias_report_hours = v"
            style="width: 60px;" />
          <template #feedback>{{ $t('config.report_time_desc') }}</template>
        </n-form-item>

        <n-divider title-position="left">{{ $t('config.news_block') }}</n-divider>
        <div style="display: flex; gap: 24px;">
          <n-form-item :label="$t('config.bearish_block_long')" style="flex: 1;">
            <n-switch :value="local.block_long_when_bias_bearish"
              @update:value="(v: boolean) => local.block_long_when_bias_bearish = v" />
            <template #feedback>{{ $t('config.bearish_block_long_desc') }}</template>
          </n-form-item>
          <n-form-item :label="$t('config.bullish_block_short')" style="flex: 1;">
            <n-switch :value="local.block_short_when_bias_bullish"
              @update:value="(v: boolean) => local.block_short_when_bias_bullish = v" />
            <template #feedback>{{ $t('config.bullish_block_short_desc') }}</template>
          </n-form-item>
        </div>

        <n-form-item v-if="local.block_long_when_bias_bearish || local.block_short_when_bias_bullish" :label="$t('config.current_bias')">
          <BiasStateIndicator />
        </n-form-item>

        <n-form-item label-placement="left" v-if="local.block_long_when_bias_bearish || local.block_short_when_bias_bullish" :label="$t('config.di_gap_threshold')">
          <app-input-number :value="local.news_bias_di_gap"
            @update:value="(v: number) => local.news_bias_di_gap = v"
            :min="0" :max="30" :step="1" style="width: 110px;" />
          <template #feedback>{{ $t('config.di_gap_desc') }}</template>
        </n-form-item>

        <n-button type="primary" :disabled="!changed" @click="save" block>
          {{ $t('config.save_news') }}
        </n-button>
      </n-space>
    </n-grid-item>

    <n-grid-item>
      <n-space vertical size="medium">
        <n-divider title-position="left">{{ $t('config.event_filter') }}</n-divider>

        <n-form-item :label="$t('config.impact_level')">
          <n-select :value="local.news_impact_filter" :options="impactOptions"
            @update:value="(v: string) => local.news_impact_filter = v" />
        </n-form-item>

        <n-form-item :label="$t('config.currency')">
          <n-input :value="local.news_currency_filter"
            @update:value="(v: string) => local.news_currency_filter = v"
            style="width: 60px;" />
          <template #feedback>{{ $t('config.currency_desc') }}</template>
        </n-form-item>

        <n-divider title-position="left">{{ $t('config.current_status') }}</n-divider>

        <n-alert v-if="calendar?.is_blackout" type="warning" :bordered="false">
          {{ $t('config.blackout_active', { reason: calendar.blackout_reason }) }}
        </n-alert>
        <n-alert v-else type="success" :bordered="false">
          {{ $t('config.trading_normal') }}
        </n-alert>

        <n-text depth="2" style="font-size: 13px;">{{ $t('config.high_impact_events') }}</n-text>
        <n-spin v-if="loading" size="small" />

        <n-empty v-else-if="!calendar || !calendar.upcoming_events?.length"
          :description="$t('config.no_events')" size="small" />

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
          {{ $t('config.refresh_events') }}
        </n-button>
      </n-space>
    </n-grid-item>
  </n-grid>
</template>