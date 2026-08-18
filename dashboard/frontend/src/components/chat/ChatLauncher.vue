<script setup lang="ts">
import { ref } from 'vue'
import AiChatPanel from './AiChatPanel.vue'

const open = ref(false)

function toggle() {
  open.value = !open.value
}
</script>

<template>
  <!-- 浮动按钮 -->
  <Transition name="launcher">
    <button v-if="!open" class="chat-launcher" @click="toggle" title="问金探">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>
      </svg>
    </button>
  </Transition>

  <!-- 聊天面板 -->
  <Transition name="panel">
    <div v-if="open" class="chat-panel-wrapper">
      <AiChatPanel @close="toggle" />
    </div>
  </Transition>
</template>

<style scoped>
.chat-launcher {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, #f0b90b, #d4a309);
  border: none;
  color: #0d1117;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 20px rgba(240, 185, 11, 0.4);
  z-index: 9999;
  transition: all 0.2s ease;
}
.chat-launcher:hover {
  width: 60px;
  height: 60px;
  box-shadow: 0 6px 28px rgba(240, 185, 11, 0.6);
}

.chat-panel-wrapper {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
/* 关闭按钮在 AiChatPanel 内部 */

/* 动画 */
.launcher-enter-active, .launcher-leave-active {
  transition: all 0.2s ease;
}
.launcher-enter-from, .launcher-leave-to {
  opacity: 0;
  transform: scale(0.5);
}

.panel-enter-active, .panel-leave-active {
  transition: all 0.25s ease;
}
.panel-enter-from, .panel-leave-to {
  opacity: 0;
  transform: translateY(20px) scale(0.95);
}
</style>
