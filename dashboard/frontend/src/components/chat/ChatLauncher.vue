<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import AiChatPanel from './AiChatPanel.vue'

const { t } = useI18n()
const open = ref(false)

function toggle() {
  open.value = !open.value
}

// ── 启动按钮：拖动 + 位置记忆（与面板拖拽同一套 Pointer Events 模式）──
// 行为契约：仅按住鼠标左键才能拖动；悬停/移入绝不改变位置、绝不显示 grab 光标
const POS_KEY = 'ai_launcher_position'
const BTN_SIZE = 60  // 固定尺寸：不随交互变化，保证抓取偏移恒定、跟手不抖

interface LauncherPos { x: number; y: number }

// 默认位置保持原样：右下角
function defaultPos(): LauncherPos {
  return {
    x: Math.max(0, window.innerWidth - BTN_SIZE - 24),
    y: Math.max(0, window.innerHeight - BTN_SIZE - 24),
  }
}

// 按钮完整保持在视口内
function clampPos(p: LauncherPos): LauncherPos {
  return {
    x: Math.max(0, Math.min(p.x, window.innerWidth - BTN_SIZE)),
    y: Math.max(0, Math.min(p.y, window.innerHeight - BTN_SIZE)),
  }
}

function loadPos(): LauncherPos {
  try {
    const raw = localStorage.getItem(POS_KEY)
    if (raw) {
      const p = JSON.parse(raw)
      if (typeof p.x === 'number' && typeof p.y === 'number') return clampPos(p)
    }
  } catch { /* 数据损坏回退默认 */ }
  return defaultPos()
}

const pos = ref<LauncherPos>(loadPos())
const dragging = ref(false)
// 拖动状态机：isDown 是唯一的「按住」事实来源，只在左键 pointerdown 置 true，
// 在 pointerup/pointercancel 置 false。pointermove 无 isDown 一律直接返回。
let isDown = false
let downAt = { x: 0, y: 0 }
// 按下瞬间「鼠标相对按钮左上角」的抓取偏移，拖动全程恒定 → 按钮立即粘住鼠标、无跳动
let grabOffset = { x: 0, y: 0 }
let lastClickAt = 0        // 双击判定：上次点击（位移<5px）时间
let lastPointerUpAt = 0    // 鼠标触发的 click 事件去重

function savePos() {
  try { localStorage.setItem(POS_KEY, JSON.stringify(pos.value)) } catch { /* ignore */ }
}

function onPointerDown(e: PointerEvent) {
  // 只响应鼠标左键（触摸/笔 pointerType 无 button 概念，button===0 同样通过）
  if (e.button !== 0) return
  isDown = true
  downAt = { x: e.clientX, y: e.clientY }
  grabOffset = { x: e.clientX - pos.value.x, y: e.clientY - pos.value.y }
  try { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId) } catch { /* ignore */ }
  e.preventDefault()
}

function onPointerMove(e: PointerEvent) {
  // ★ 核心守卫：未按住（悬停/移入）绝不产生任何位置变化
  if (!isDown) return
  const dx = e.clientX - downAt.x
  const dy = e.clientY - downAt.y
  // 位移 < 5px 视为点击；≥ 5px 进入拖动
  if (!dragging.value) {
    if (Math.abs(dx) < 5 && Math.abs(dy) < 5) return
    dragging.value = true
  }
  // 绝对定位：鼠标位置 - 恒定抓取偏移（非每帧对准中心，按下瞬间不跳动）
  pos.value = clampPos({ x: e.clientX - grabOffset.x, y: e.clientY - grabOffset.y })
}

function endDrag(e: PointerEvent) {
  try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId) } catch { /* ignore */ }
  isDown = false
}

function onPointerUp(e: PointerEvent) {
  if (!isDown) return  // 未按住的 pointerup（理论上不会到达，双保险）
  endDrag(e)
  lastPointerUpAt = Date.now()
  if (dragging.value) {
    dragging.value = false
    savePos()
    lastClickAt = 0  // 拖动结束的这次按下不计入双击
    return
  }
  // 点击：两次间隔 < 500ms 才打开（双击），避免拖动/误击误开
  const now = Date.now()
  if (now - lastClickAt < 500) {
    lastClickAt = 0
    open.value = true
  } else {
    lastClickAt = now
  }
}

// 捕获被系统中断（如 alt-tab、触摸手势取消）：可靠复位状态机，避免残留拖动态
function onPointerCancel(e: PointerEvent) {
  endDrag(e)
  dragging.value = false
}

// 键盘可访问性：Enter/Space 直接打开（无需双击）；鼠标产生的 click 事件去重跳过
function onClick() {
  if (Date.now() - lastPointerUpAt < 500) return
  open.value = true
}

// 窗口尺寸变化时修正越界位置
function onWindowResize() {
  pos.value = clampPos(pos.value)
}

onMounted(() => window.addEventListener('resize', onWindowResize))
onBeforeUnmount(() => window.removeEventListener('resize', onWindowResize))
</script>

<template>
  <!-- 浮动按钮（按住左键拖动，双击打开，位置记忆） -->
  <Transition name="launcher">
    <button v-if="!open" class="chat-launcher" :class="{ dragging }"
      :style="{ left: pos.x + 'px', top: pos.y + 'px', cursor: dragging ? 'grabbing' : 'pointer' }"
      @pointerdown="onPointerDown" @pointermove="onPointerMove" @pointerup="onPointerUp"
      @pointercancel="onPointerCancel" @click="onClick" @dragstart.prevent
      draggable="false" :title="t('ai.launcher_open_hint')">
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
/* 固定 60px 尺寸：尺寸恒定不随交互变化，抓取偏移稳定 → 按住拖动全程跟手无抖动 */
.chat-launcher {
  position: fixed;
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background: linear-gradient(135deg, #f0b90b, #d4a309);
  border: none;
  color: #0d1117;
  cursor: pointer;  /* 默认/悬停一律 pointer；仅按住拖动中（内联 + .dragging）为 grabbing */
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 20px rgba(240, 185, 11, 0.4);
  z-index: 9999;
  /* 只过渡阴影；绝不过渡 left/top/transform，避免拖动滞后与抖动 */
  transition: box-shadow 0.2s ease;
  touch-action: none;
  user-select: none;
}
/* hover 仅加深阴影：不改尺寸、不改光标、不产生任何位置变化 */
.chat-launcher:hover {
  box-shadow: 0 6px 28px rgba(240, 185, 11, 0.6);
  cursor: pointer;
}
/* 按住拖动中：轻微放大 + 加强阴影 + grabbing 光标。
   transform-origin 锁定左上角：放大只向右下扩展，定位锚点纹丝不动、零抖动 */
.chat-launcher.dragging {
  cursor: grabbing;
  transform: scale(1.08);
  transform-origin: 0 0;
  box-shadow: 0 8px 32px rgba(240, 185, 11, 0.7);
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
