<script setup lang="ts">
// 招财金探形象（手绘 SVG，零外部资源）：桌面入口桌宠 / 面板标题栏 / 消息头像共用
// - size：渲染尺寸（px）
// - animated：是否启用待机动画（桌宠为 true；头像/标题栏图标保持静态）
// - state：idle / thinking（流式工作态）/ complete（完成庆祝，播一次）
// - blink：一次性眨眼微表情
withDefaults(defineProps<{
  size?: number
  animated?: boolean
  state?: 'idle' | 'thinking' | 'complete'
  blink?: boolean
}>(), {
  size: 28,
  animated: false,
  state: 'idle',
  blink: false,
})
</script>

<template>
  <span
    class="fortune-cat"
    :class="{
      'fc--anim': animated && state === 'idle',
      'fc--thinking': state === 'thinking',
      'fc--complete': state === 'complete',
      'fc--blink': blink,
    }"
    aria-hidden="true"
  >
    <svg :width="size" :height="size" viewBox="0 0 44 44" fill="none">
      <g class="fc-bob">
        <!-- 思考态头顶省略号 -->
        <g class="fc-dots">
          <circle cx="13" cy="6" r="1.4"/>
          <circle cx="17.5" cy="3.6" r="1.4"/>
          <circle cx="22" cy="2.4" r="1.4"/>
        </g>
        <!-- 金元宝（完成态闪光） -->
        <g class="fc-ingot">
          <path d="M5.6 40.8 Q11.5 33.4 17.4 40.8 L15.6 42.4 L7.4 42.4 Z" fill="#f6c445" stroke="#6b4a12" stroke-width="1.2" stroke-linejoin="round"/>
          <ellipse cx="11.5" cy="38.6" rx="2.8" ry="1.9" fill="#ffe08a" stroke="#6b4a12" stroke-width="0.9"/>
        </g>
        <!-- 左耳 / 右耳 -->
        <path class="fc-ear" d="M11 14 L9.4 4.6 L18 9.6 Z" fill="#f0b90b" stroke="#6b4a12" stroke-width="1.5" stroke-linejoin="round"/>
        <path class="fc-ear" d="M33 14 L34.6 4.6 L26 9.6 Z" fill="#f0b90b" stroke="#6b4a12" stroke-width="1.5" stroke-linejoin="round"/>
        <!-- 圆脸 -->
        <circle cx="22" cy="19" r="12.2" fill="#f0b90b" stroke="#6b4a12" stroke-width="1.5"/>
        <!-- 暖白口鼻区 -->
        <ellipse cx="22" cy="23.8" rx="6.8" ry="4.8" fill="#fff6dd"/>
        <!-- 眼睛：常态（眨眼用） -->
        <g class="fc-eyes">
          <circle cx="17.2" cy="17.6" r="1.6" fill="#4a3208"/>
          <circle cx="26.8" cy="17.6" r="1.6" fill="#4a3208"/>
        </g>
        <!-- 眯眼笑（完成态显示） -->
        <g class="fc-eyes-happy">
          <path d="M15 18.2 Q17.2 15.8 19.4 18.2" stroke="#4a3208" stroke-width="1.5" fill="none" stroke-linecap="round"/>
          <path d="M24.6 18.2 Q26.8 15.8 29 18.2" stroke="#4a3208" stroke-width="1.5" fill="none" stroke-linecap="round"/>
        </g>
        <!-- 鼻 + 嘴 -->
        <circle cx="22" cy="21.6" r="1" fill="#b3722a"/>
        <path d="M19.8 24.2 Q22 26.4 24.2 24.2" stroke="#6b4a12" stroke-width="1.3" fill="none" stroke-linecap="round"/>
        <!-- 胡须 -->
        <g stroke="#8a6a2f" stroke-width="0.9" stroke-linecap="round">
          <path d="M7.2 18.4 L11.4 19.2"/><path d="M7.4 21.8 L11.5 21.5"/>
          <path d="M32.6 19.2 L36.8 18.4"/><path d="M32.5 21.5 L36.6 21.8"/>
        </g>
        <!-- 颈铃 -->
        <circle cx="22" cy="31.8" r="2.1" fill="#f6c445" stroke="#6b4a12" stroke-width="1"/>
        <path d="M22 32.6 L22 33.8" stroke="#6b4a12" stroke-width="0.9" stroke-linecap="round"/>
        <!-- 举起的招财爪（左臂+掌，肩部为摆动轴） -->
        <g class="fc-paw">
          <path d="M12.4 26 L6.6 17.2" stroke="#f0b90b" stroke-width="4.8" stroke-linecap="round"/>
          <circle cx="6.2" cy="15.2" r="3" fill="#fff6dd" stroke="#6b4a12" stroke-width="1.3"/>
        </g>
        <!-- 怀中铜钱 -->
        <g>
          <circle cx="30.5" cy="33.6" r="4.2" fill="#f6c445" stroke="#6b4a12" stroke-width="1.2"/>
          <rect x="29" y="32.1" width="3" height="3" fill="#fff6dd" stroke="#6b4a12" stroke-width="0.8"/>
        </g>
      </g>
    </svg>
  </span>
</template>

<style scoped>
.fortune-cat {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;  /* 纯视觉形象，不抢交互命中 */
}
.fc-eyes, .fc-eyes-happy, .fc-dots, .fc-ingot { transform-box: fill-box; }
.fc-eyes { transform-origin: 50% 50%; }
.fc-eyes-happy, .fc-dots { display: none; }
.fc-dots circle { fill: #fff6dd; opacity: 0; }

/* 动画只动 transform/opacity（GPU 友好）；仅桌宠启用（.fc--anim / 思考 / 完成） */
.fc--anim .fc-bob {
  transform-box: view-box;
  transform-origin: 22px 24px;
  animation: fc-bob 2.8s ease-in-out infinite;
}
.fc--anim .fc-paw {
  transform-box: view-box;
  transform-origin: 12.4px 26px;
  animation: fc-wave-slow 2.4s ease-in-out infinite;
}
@keyframes fc-bob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-1.6px); }
}
@keyframes fc-wave-slow {
  0%, 100% { transform: rotate(0deg); }
  50% { transform: rotate(-14deg); }
}

/* 思考/工作态：微微前倾 + 爪子摆动加快 + 头顶省略号浮动 */
.fc--thinking .fc-bob {
  transform-box: view-box;
  transform-origin: 22px 24px;
  animation: fc-tilt 1.4s ease-in-out infinite;
}
.fc--thinking .fc-paw {
  transform-box: view-box;
  transform-origin: 12.4px 26px;
  animation: fc-wave-fast 0.9s ease-in-out infinite;
}
.fc--thinking .fc-dots { display: block; }
.fc--thinking .fc-dots circle { animation: fc-dot 1.1s ease-in-out infinite; }
.fc--thinking .fc-dots circle:nth-child(2) { animation-delay: 0.18s; }
.fc--thinking .fc-dots circle:nth-child(3) { animation-delay: 0.36s; }
@keyframes fc-tilt {
  0%, 100% { transform: translateY(0) rotate(2.5deg); }
  50% { transform: translateY(-1px) rotate(-1.5deg); }
}
@keyframes fc-wave-fast {
  0%, 100% { transform: rotate(4deg); }
  50% { transform: rotate(-22deg); }
}
@keyframes fc-dot {
  0%, 100% { opacity: 0; transform: translateY(0.5px); }
  50% { opacity: 0.95; transform: translateY(-1px); }
}

/* 完成：一次短促庆祝（眯眼笑 + 金元宝闪光 + 轻跳） */
.fc--complete .fc-bob {
  transform-box: view-box;
  transform-origin: 22px 24px;
  animation: fc-hop 0.8s ease-out 1;
}
.fc--complete .fc-eyes { display: none; }
.fc--complete .fc-eyes-happy { display: block; }
.fc--complete .fc-ingot { animation: fc-flash 0.8s ease-out 1; }
@keyframes fc-hop {
  0%, 100% { transform: translateY(0) rotate(0deg) scale(1); }
  30% { transform: translateY(-3px) rotate(-4deg) scale(1.05); }
  60% { transform: translateY(0) rotate(3deg) scale(0.98); }
}
@keyframes fc-flash {
  0%, 100% { opacity: 0.6; transform: scale(1); }
  35% { opacity: 1; transform: scale(1.18); }
  70% { opacity: 0.85; transform: scale(1); }
}

/* 单击微表情：眨眼一次（眼睛纵向压扁） */
.fc--blink .fc-eyes { animation: fc-blink 0.5s ease-out 1; }
@keyframes fc-blink {
  0%, 100% { transform: scaleY(1); }
  40% { transform: scaleY(0.08); }
}

/* 尊重系统「减弱动画」：只保留静态形象 */
@media (prefers-reduced-motion: reduce) {
  .fc--anim .fc-bob, .fc--anim .fc-paw,
  .fc--thinking .fc-bob, .fc--thinking .fc-paw,
  .fc--thinking .fc-dots circle,
  .fc--complete .fc-bob, .fc--complete .fc-ingot,
  .fc--blink .fc-eyes {
    animation: none !important;
  }
}
</style>
