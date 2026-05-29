<script setup lang="ts">
import { useAccountStore } from '@/stores/account'

const account = useAccountStore()
</script>

<template>
  <n-card title="账户信息" :bordered="true" size="small">
    <!-- 加载态 -->
    <template v-if="account.loading">
      <n-skeleton text :repeat="3" />
    </template>
    <!-- 错误态 -->
    <template v-else-if="account.error">
      <n-result status="error" title="获取账户信息失败" :description="account.error" size="small">
        <template #footer>
          <n-button size="small" @click="account.fetch()">重试</n-button>
        </template>
      </n-result>
    </template>
    <!-- 空态（未连接） -->
    <template v-else-if="!account.info">
      <n-result status="info" title="等待连接" description="MT4 未连接，启动引擎后自动获取">
        <template #icon>
          <n-icon size="48"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm1-13h-2v6l5.25 3.15L17 12.23l-4-2.37V7z"/></svg></n-icon>
        </template>
      </n-result>
    </template>
    <!-- 数据态 -->
    <template v-else>
      <n-grid :cols="4" :x-gap="12" :y-gap="12">
        <n-gi>
          <n-statistic label="余额" tabular-nums>
            <span class="price-gold">${{ account.info.balance.toFixed(2) }}</span>
          </n-statistic>
        </n-gi>
        <n-gi>
          <n-statistic label="净值" tabular-nums>
            <span :class="account.info.equity >= account.info.balance ? 'price-up' : 'price-down'">
              ${{ account.info.equity.toFixed(2) }}
            </span>
          </n-statistic>
        </n-gi>
        <n-gi>
          <n-statistic label="已用保证金" tabular-nums>
            ${{ account.info.margin.toFixed(2) }}
          </n-statistic>
        </n-gi>
        <n-gi>
          <n-statistic label="可用保证金" tabular-nums>
            ${{ account.info.free_margin.toFixed(2) }}
          </n-statistic>
        </n-gi>
      </n-grid>
      <n-descriptions :column="3" size="small" bordered style="margin-top: 12px;">
        <n-descriptions-item label="账户">
          <n-tag size="small" round>{{ account.info.login }}</n-tag>
        </n-descriptions-item>
        <n-descriptions-item label="杠杆">1:{{ account.info.leverage }}</n-descriptions-item>
        <n-descriptions-item label="货币">{{ account.info.currency }}</n-descriptions-item>
      </n-descriptions>
    </template>
  </n-card>
</template>
