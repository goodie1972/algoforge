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

// 下拉选项
const commonMinOpts = [0,5,10,15,20,30,45,60,90,120,180,240,360].map(v => ({ label: String(v), value: v }))
const reportHourOpts = ['0,12','8,20','0,8,16','0,4,8,12,16,20'].map(v => ({ label: v, value: v }))
const diGapOpts = [0,1,2,3,4,5,6,8,10,12,15,20,25,30].map(v => ({ label: String(v), value: v }))
const currencyOpts = ['USD','EUR','GBP','JPY','CNY','AUD','CAD','CHF'].map(v => ({ label: v, value: v }))
</script>

<template>
  <n-space vertical size="large">
    <!-- 左列 -->
    <n-grid :cols="2" :x-gap="24">
      <n-grid-item>
        <n-space vertical size="medium">
          <!-- 卡片1: 新闻过滤 -->
          <n-card size="small" :bordered="true">
            <template #header>
              <div style="display:flex;align-items:center;gap:6px;width:100%;">
                <span>{{ $t('config.news_filter') }}</span>
                <n-popover trigger="hover" placement="right">
                  <template #trigger><n-button text circle size="tiny" filterable tag class="help-btn">?</n-button></template>
                  <div style="max-width:280px;font-size:12px;line-height:1.7;white-space:pre-line;">{{ $t('config.card_news_filter_help') }}</div>
                </n-popover>
              </div>
            </template>
            <n-form-item :label="$t('config.news_filter_enable')">
              <n-switch :value="local.news_filter_enabled" @update:value="(v: boolean) => local.news_filter_enabled = v" />
            </n-form-item>
            <n-grid :cols="2" :x-gap="12">
              <n-grid-item>
                <n-form-item label-placement="left" :label="$t('config.before_release')">
                  <n-select :value="local.news_before_minutes" :options="commonMinOpts" size="tiny" filterable tag
                    @update:value="(v: any) => v !== null && (local.news_before_minutes = v)" style="width: 80px;" />
                </n-form-item>
              </n-grid-item>
              <n-grid-item>
                <n-form-item label-placement="left" :label="$t('config.after_release')">
                  <n-select :value="local.news_after_minutes" :options="commonMinOpts" size="tiny" filterable tag
                    @update:value="(v: any) => v !== null && (local.news_after_minutes = v)" style="width: 80px;" />
                </n-form-item>
              </n-grid-item>
            </n-grid>
          </n-card>

          <!-- 卡片2: 新闻偏向 -->
          <n-card size="small" :bordered="true">
            <template #header>
              <div style="display:flex;align-items:center;gap:6px;width:100%;">
                <span>{{ $t('config.news_bias') }}</span>
                <n-popover trigger="hover" placement="right">
                  <template #trigger><n-button text circle size="tiny" filterable tag class="help-btn">?</n-button></template>
                  <div style="max-width:280px;font-size:12px;line-height:1.7;white-space:pre-line;">{{ $t('config.card_news_bias_help') }}</div>
                </n-popover>
              </div>
            </template>
            <n-form-item :label="$t('config.news_bias_enable')">
              <n-switch :value="local.news_bias_enabled" @update:value="(v: boolean) => local.news_bias_enabled = v" />
              <template #feedback>{{ $t('config.news_bias_desc') }}</template>
            </n-form-item>
            <n-grid :cols="2" :x-gap="12">
              <n-grid-item>
                <n-form-item label-placement="left" :label="$t('config.report_time_utc')">
                  <n-select :value="local.news_bias_report_hours" :options="reportHourOpts" size="tiny" filterable tag
                    @update:value="(v: string) => local.news_bias_report_hours = v" style="width: 80px;" />
                  <template #feedback>{{ $t('config.report_time_desc') }}</template>
                </n-form-item>
              </n-grid-item>
            </n-grid>
            <n-grid :cols="2" :x-gap="12">
              <n-grid-item>
                <n-form-item :label="$t('config.bearish_block_long')">
                  <n-switch :value="local.block_long_when_bias_bearish" @update:value="(v: boolean) => local.block_long_when_bias_bearish = v" />
                  <template #feedback>{{ $t('config.bearish_block_long_desc') }}</template>
                </n-form-item>
              </n-grid-item>
              <n-grid-item>
                <n-form-item :label="$t('config.bullish_block_short')">
                  <n-switch :value="local.block_short_when_bias_bullish" @update:value="(v: boolean) => local.block_short_when_bias_bullish = v" />
                  <template #feedback>{{ $t('config.bullish_block_short_desc') }}</template>
                </n-form-item>
              </n-grid-item>
            </n-grid>
            <n-form-item v-if="local.block_long_when_bias_bearish || local.block_short_when_bias_bullish" :label="$t('config.current_bias')">
              <BiasStateIndicator />
            </n-form-item>
            <n-form-item label-placement="left" v-if="local.block_long_when_bias_bearish || local.block_short_when_bias_bullish" :label="$t('config.di_gap_threshold')">
              <n-select :value="local.news_bias_di_gap" :options="diGapOpts" size="tiny" filterable tag
                @update:value="(v: number) => local.news_bias_di_gap = v" style="width: 80px;" />
              <template #feedback>{{ $t('config.di_gap_desc') }}</template>
            </n-form-item>
          </n-card>

          <n-button type="primary" :disabled="!changed" @click="save" block>
            {{ $t('config.save_news') }}
          </n-button>
        </n-space>
      </n-grid-item>

      <!-- 右列 -->
      <n-grid-item>
        <n-space vertical size="medium">
          <!-- 卡片3: 事件过滤 -->
          <n-card size="small" :bordered="true">
            <template #header>
              <div style="display:flex;align-items:center;gap:6px;width:100%;">
                <span>{{ $t('config.event_filter') }}</span>
                <n-popover trigger="hover" placement="right">
                  <template #trigger><n-button text circle size="tiny" filterable tag class="help-btn">?</n-button></template>
                  <div style="max-width:280px;font-size:12px;line-height:1.7;white-space:pre-line;">{{ $t('config.card_event_filter_help') }}</div>
                </n-popover>
              </div>
            </template>
            <n-grid :cols="2" :x-gap="12">
              <n-grid-item>
                <n-form-item :label="$t('config.impact_level')">
                  <n-select :value="local.news_impact_filter" :options="impactOptions" size="tiny" filterable tag
                    @update:value="(v: string) => local.news_impact_filter = v" style="width: 100px;" />
                </n-form-item>
              </n-grid-item>
              <n-grid-item>
                <n-form-item :label="$t('config.currency')">
                  <n-select :value="local.news_currency_filter" :options="currencyOpts" size="tiny" filterable tag
                    @update:value="(v: string) => local.news_currency_filter = v" style="width: 100px;" />
                  <template #feedback>{{ $t('config.currency_desc') }}</template>
                </n-form-item>
              </n-grid-item>
            </n-grid>
          </n-card>

          <!-- 当前状态 -->
          <n-card size="small" :bordered="true" :title="$t('config.current_status')">
            <n-alert v-if="calendar?.is_blackout" type="warning" :bordered="false">
              {{ $t('config.blackout_active', { reason: calendar.blackout_reason }) }}
            </n-alert>
            <n-alert v-else type="success" :bordered="false">
              {{ $t('config.trading_normal') }}
            </n-alert>
            <n-text depth="2" style="font-size:13px;display:block;margin-top:8px;">{{ $t('config.high_impact_events') }}</n-text>
            <n-spin v-if="loading" size="small" />
            <n-empty v-else-if="!calendar || !calendar.upcoming_events?.length" :description="$t('config.no_events')" size="small" />
            <div v-else v-for="evt in calendar.upcoming_events.slice(0, 10)" :key="evt.datetime + evt.title"
              style="display:flex;align-items:center;justify-content:space-between;padding:6px 8px;margin-bottom:4px;border-radius:4px;background:var(--n-color-embedded);font-size:13px;">
              <div style="flex:1;">
                <n-text>{{ evt.title }}</n-text>
                <n-text depth="3" style="margin-left:6px;">{{ evt.country }}</n-text>
              </div>
              <div style="text-align:right;">
                <n-tag :type="evt.impact === 'High' ? 'error' : 'warning'" size="tiny" filterable tag>{{ evt.impact }}</n-tag>
                <n-text depth="3" style="margin-left:6px;font-size:11px;">{{ evt.datetime }}</n-text>
              </div>
            </div>
            <n-button @click="refreshCalendar" size="small" secondary style="margin-top:8px;">{{ $t('config.refresh_events') }}</n-button>
          </n-card>
        </n-space>
      </n-grid-item>
    </n-grid>
  </n-space>
</template>

<style scoped>
.help-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 50%;
  border: 1.5px solid #8b8f97; color: #8b8f97;
  font-size: 11px; font-weight: 700; cursor: pointer;
  background: transparent; line-height: 1;
  transition: border-color 0.2s, color 0.2s;
}
.help-btn:hover { border-color: #f0b90b; color: #f0b90b; }
</style>