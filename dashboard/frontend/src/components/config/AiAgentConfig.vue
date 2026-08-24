<script setup lang="ts">
// 布局容器：各区块的状态、数据加载与交互逻辑均已拆分至 ./agent/ 下的子组件
// 区块顺序：LLM 供应商 → Agent 运行设置 → 人设 → 技能 → MCP 连接器 → 工具
import ProviderSection from './agent/ProviderSection.vue'
import AgentSettingsSection from './agent/AgentSettingsSection.vue'
import PersonaSection from './agent/PersonaSection.vue'
import SkillsSection from './agent/SkillsSection.vue'
import McpSection from './agent/McpSection.vue'
import ToolsSection from './agent/ToolsSection.vue'
</script>

<template>
  <div>
    <ProviderSection />
    <AgentSettingsSection />
    <PersonaSection />
    <SkillsSection />
    <McpSection />
    <ToolsSection />
  </div>
</template>
