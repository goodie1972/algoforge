<script setup lang="ts">
import { ref, onMounted } from 'vue'

// ── 工具注册表 ──
const tools = ref<any[]>([])
async function loadTools() {
  try {
    const r = await fetch('/api/ai/tools')
    const d = await r.json()
    tools.value = d.tools || []
  } catch (e) { /* ignore */ }
}

// 工具参数简化展示："参数名: 描述"
function toolParams(tool: any): string[] {
  const props = tool.parameters?.properties || {}
  return Object.entries(props).map(([k, v]: [string, any]) =>
    v?.description ? `${k}: ${v.description}` : k)
}

onMounted(loadTools)
</script>

<template>
  <n-card size="small" :bordered="true">
    <template #header>
      <span>可用工具 ({{ tools.length }})</span>
    </template>
    <n-space vertical v-if="tools.length > 0">
      <n-card v-for="tool in tools" :key="tool.name" size="small">
        <template #header>
          <span style="font-weight:600">{{ tool.name }}</span>
          <n-tag v-if="tool.category" size="tiny" :bordered="false" style="margin-left:8px">{{ tool.category }}</n-tag>
        </template>
        <div style="font-size:13px;color:#8b8f97;margin-bottom:6px">{{ tool.description }}</div>
        <n-space v-if="toolParams(tool).length" size="small">
          <n-tag v-for="p in toolParams(tool)" :key="p" size="tiny" :bordered="false">{{ p }}</n-tag>
        </n-space>
      </n-card>
    </n-space>
    <n-empty v-else description="暂无工具" />
  </n-card>
</template>
