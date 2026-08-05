<script setup lang="ts">
import { computed, ref, reactive, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()

const local = reactive({
  review_enabled: store.items.review_enabled ?? true,
  review_accuracy_threshold: store.items.review_accuracy_threshold ?? 50,
  review_interval_hours: store.items.review_interval_hours ?? 6,
  _current_accuracy: 0,
  _current_bias: '',
  _total_reviews: 0,
  _correct_count: 0,
})

const original = computed(() => ({
  review_enabled: store.items.review_enabled ?? true,
  review_accuracy_threshold: store.items.review_accuracy_threshold ?? 50,
  review_interval_hours: store.items.review_interval_hours ?? 6,
}))

const changed = computed(() =>
  local.review_enabled !== original.value.review_enabled ||
  local.review_accuracy_threshold !== original.value.review_accuracy_threshold ||
  local.review_interval_hours !== original.value.review_interval_hours
)

async function save() {
  const { _current_accuracy, _current_bias, _total_reviews, _correct_count, ...data } = local
  await store.update(data)
  message.success('AI 配置已保存')
}

async function loadStats() {
  try {
    const res = await fetch('/api/news-review/stats?days=7')
    const d = await res.json()
    if (d.success) {
      local._current_accuracy = d.data?.summary?.accuracy ?? 0
      local._total_reviews = d.data?.summary?.total_reviews ?? 0
      local._correct_count = d.data?.summary?.correct ?? 0
    }
  } catch { /* ignore */ }
  try {
    const res = await fetch('/api/engine/status')
    const d = await res.json()
    if (d.bias_direction) local._current_bias = d.bias_direction
  } catch { /* ignore */ }
}

onMounted(loadStats)

const accuracyColor = computed(() => {
  const a = local._current_accuracy
  if (a >= 50) return '#0ecb81'
  if (a >= 30) return '#f0b90b'
  return '#f6465d'
})
</script>

<template>
  <n-grid :cols="2" :x-gap="24" :y-gap="12">
    <n-grid-item>
      <n-space vertical size="medium">

        <n-form-item label="启用 AI 复盘 Agent">
          <n-switch :value="local.review_enabled"
            @update:value="(v: boolean) => local.review_enabled = v" />
          <template #feedback>自动运行新闻预判复盘分析，比对预测与实际走势</template>
        </n-form-item>

        <n-form-item label="复盘间隔">
          <app-input-number :value="local.review_interval_hours"
            @update:value="(v: number) => local.review_interval_hours = v"
            :min="1" :max="24" :step="1" style="width: 110px;" />
          <template #feedback>每隔 N 小时自动复盘一次</template>
        </n-form-item>

        <n-form-item label="准确率门限">
          <app-input-number :value="local.review_accuracy_threshold"
            @update:value="(v: number) => local.review_accuracy_threshold = v"
            :min="0" :max="100" :step="5" style="width: 110px;" />
          <template #feedback>低于此准确率时，偏误方向自动切换为 neutral，不阻塞交易</template>
        </n-form-item>

        <n-button type="primary" :disabled="!changed" @click="save" block style="margin-top:32px">
          保存 AI 配置
        </n-button>

      </n-space>
    </n-grid-item>

    <n-grid-item>
      <n-space vertical size="medium">

        <n-divider title-position="left">Agent 运行状态</n-divider>

        <n-card size="small" :bordered="true">
          <n-space vertical>
            <n-thing>
              <template #description>
                <n-space vertical size="small">
                  <div style="display:flex;justify-content:space-between">
                    <span>当前偏误方向</span>
                    <n-tag :bordered="false" :type="local._current_bias === 'bullish' ? 'success' : local._current_bias === 'bearish' ? 'error' : 'default'" size="small">
                      {{ local._current_bias || 'neutral' }}
                    </n-tag>
                  </div>
                  <div style="display:flex;justify-content:space-between">
                    <span>累计复盘</span>
                    <n-tag bordered="false" size="small">{{ local._total_reviews }} 条</n-tag>
                  </div>
                  <div style="display:flex;justify-content:space-between">
                    <span>正确预测</span>
                    <n-tag :bordered="false" :type="local._correct_count > 0 ? 'success' : 'default'" size="small">
                      {{ local._correct_count }} 条
                    </n-tag>
                  </div>
                  <div style="display:flex;justify-content:space-between">
                    <span>准确率</span>
                    <n-tag :bordered="false" :type="local._current_accuracy >= 50 ? 'success' : local._current_accuracy >= 30 ? 'warning' : 'error'" size="small">
                      {{ local._current_accuracy }}%
                    </n-tag>
                  </div>
                </n-space>
              </template>
            </n-thing>
          </n-space>
        </n-card>

        <n-divider title-position="left">自动修正策略</n-divider>

        <n-card size="small" :bordered="true">
          <n-space vertical size="small">
            <n-text depth="2">准确率低于门限时自动执行：</n-text>
            <n-alert type="success" :bordered="false" closable>
              <strong>偏误方向 → neutral</strong><br>
              不阻塞任何方向的开仓，让技术指标自由交易
            </n-alert>
            <n-alert type="warning" :bordered="false" closable>
              <strong>复盘频率调整</strong><br>
              准确率持续偏低时，自动缩短复盘间隔
            </n-alert>
            <n-alert type="info" :bordered="false" closable>
              <strong>偏差类型分析</strong><br>
              自动归类偏差原因（数据反直觉/技术面压制/提前消化等）
            </n-alert>
          </n-space>
        </n-card>

        <n-button @click="loadStats" size="small" secondary>
          刷新状态
        </n-button>

      </n-space>
    </n-grid-item>
  </n-grid>
</template>