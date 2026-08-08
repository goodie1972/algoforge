<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ data: any }>()
const emit = defineEmits<{ close: [] }>()

const router = useRouter()
const { t } = useI18n()

function nbDir(dir: string): string {
  if (dir === 'bullish') return t('news.bullish')
  if (dir === 'bearish') return t('news.bearish')
  return t('news.neutral')
}
function nbDirTag(dir: string): string {
  if (dir === 'bullish') return 'success'
  if (dir === 'bearish') return 'error'
  return 'warning'
}
function nbDirLabel(dir: string): string {
  return dir === 'bullish' ? t('news.bullish_impact') : dir === 'bearish' ? t('news.bearish_impact') : t('news.neutral_impact')
}
function handleGoReport() {
  emit('close')
  router.push('/report')
}
</script>

<template>
  <div class="popup-content">
    <div class="popup-header">
      <n-tag :type="nbDirTag(data.prediction?.direction)" size="large" :bordered="false"
        style="font-size: 16px; padding: 4px 16px;">
        {{ nbDir(data.prediction?.direction) }}
      </n-tag>
      <div>
        <span class="label">{{ t('news.score') }}</span>
        <span :style="{ fontWeight: 700, color: (data.prediction?.score ?? 0) > 0 ? '#0ecb81' : '#f6465d' }">
          {{ (data.prediction?.score ?? 0).toFixed(2) }}
        </span>
      </div>
      <div>
        <span class="label">{{ t('news.confidence') }}</span>
        <span style="font-weight: 700;">{{ data.prediction?.confidence ?? 0 }}%</span>
      </div>
    </div>

    <div class="reason-text">{{ data.prediction?.reason }}</div>

    <n-divider style="margin: 8px 0;">{{ t('news.key_news') }}</n-divider>

    <div v-if="data.news_items?.length">
      <div v-for="(item, idx) in data.news_items.slice(0, 5)" :key="idx" class="news-item">
        <div class="news-tags">
          <n-tag size="tiny" type="info" :bordered="false">{{ item.source }}</n-tag>
          <n-tag size="tiny" :type="nbDirTag(item.direction)" :bordered="false">
            {{ nbDirLabel(item.direction) }}
          </n-tag>
        </div>
        <span class="news-title">{{ item.title?.length > 60 ? item.title.slice(0, 60) : item.title }}</span>
        <div v-if="item.chain" class="chain-text">{{ item.chain }}</div>
      </div>
    </div>
    <n-empty v-else :description="t('news.no_data')" style="padding: 12px;" />

    <div class="popup-footer">
      <n-text depth="3" style="font-size: 12px;">{{ data.created_at }}</n-text>
      <n-button type="primary" size="small" @click="handleGoReport">{{ t('news.view_detail') }}</n-button>
    </div>
  </div>
</template>

<style scoped>
.popup-content { padding: 0; }
.popup-header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.label { color: #888; font-size: 12px; margin-right: 4px; }
.reason-text { font-size: 13px; color: #aaa; margin-bottom: 12px; line-height: 1.5; }
.news-item { padding: 6px 0; border-bottom: 1px solid #2a2a2a; font-size: 13px; }
.news-tags { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }
.news-title { color: #ccc; }
.chain-text { font-size: 11px; color: #888; margin-top: 2px; }
.popup-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 16px; }
</style>
