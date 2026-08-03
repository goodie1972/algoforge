<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAccountStore } from '@/stores/account'

const account = useAccountStore()

function flashOnChange(getter: () => number) {
  const flash = ref(false)
  let timer: any = null, last = getter()
  watch(getter, (n) => {
    if (Math.abs(n - last) < 0.01) return
    last = n; flash.value = true
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => { flash.value = false }, 600)
  })
  return flash
}

const balFlash = flashOnChange(() => account.info?.balance ?? 0)
const eqFlash = flashOnChange(() => account.info?.equity ?? 0)
const marginFlash = flashOnChange(() => account.info?.margin ?? 0)
const freeFlash = flashOnChange(() => account.info?.free_margin ?? 0)
</script>

<template>
  <n-card :title="$t('account.title')" :bordered="true" size="small">
    <!-- 加载态 -->
    <template v-if="account.loading">
      <n-skeleton text :repeat="3" />
    </template>
    <!-- 错误态 -->
    <template v-else-if="account.error">
      <n-result status="error" :title="$t('account.load_fail')" :description="account.error" size="small">
        <template #footer>
          <n-button size="small" @click="account.fetch()">{{ $t('common.retry') }}</n-button>
        </template>
      </n-result>
    </template>
    <!-- 空态（未连接） -->
    <template v-else-if="!account.info">
      <n-result status="info" :title="$t('account.waiting')" :description="$t('account.waiting_desc')">
        <template #icon>
          <n-icon size="48"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm1-13h-2v6l5.25 3.15L17 12.23l-4-2.37V7z"/></svg></n-icon>
        </template>
      </n-result>
    </template>
    <!-- 数据态 -->
    <template v-else>
      <n-grid :cols="4" :x-gap="12" :y-gap="12">
        <n-gi>
          <n-statistic :label="$t('account.balance')" tabular-nums>
            <span class="price-gold" :class="{ 'flash-num': balFlash }" style="display:inline-block;padding:1px 4px;border-radius:3px;transition:background .15s;">${{ account.info.balance.toFixed(2) }}</span>
          </n-statistic>
        </n-gi>
        <n-gi>
          <n-statistic :label="$t('account.equity')" tabular-nums>
            <span :class="[account.info.equity >= account.info.balance ? 'price-up' : 'price-down', { 'flash-num': eqFlash }]" style="display:inline-block;padding:1px 4px;border-radius:3px;transition:background .15s;">
              ${{ account.info.equity.toFixed(2) }}
            </span>
          </n-statistic>
        </n-gi>
        <n-gi>
          <n-statistic :label="$t('account.used_margin')" tabular-nums>
            <span :class="{ 'flash-num': marginFlash }" style="display:inline-block;padding:1px 4px;border-radius:3px;transition:background .15s;">${{ account.info.margin.toFixed(2) }}</span>
          </n-statistic>
        </n-gi>
        <n-gi>
          <n-statistic :label="$t('account.free_margin')" tabular-nums>
            <span :class="{ 'flash-num': freeFlash }" style="display:inline-block;padding:1px 4px;border-radius:3px;transition:background .15s;">${{ account.info.free_margin.toFixed(2) }}</span>
          </n-statistic>
        </n-gi>
      </n-grid>
      <n-descriptions :column="3" size="small" bordered style="margin-top: 12px;">
        <n-descriptions-item :label="$t('account.account')">
          <n-tag size="small" round>{{ account.info.login }}</n-tag>
        </n-descriptions-item>
        <n-descriptions-item :label="$t('account.leverage')">1:{{ account.info.leverage }}</n-descriptions-item>
        <n-descriptions-item :label="$t('account.currency')">{{ account.info.currency }}</n-descriptions-item>
      </n-descriptions>
    </template>
  </n-card>
</template>
