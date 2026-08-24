<script setup lang="ts">
// 招财金探形象（手绘 SVG，零外部资源）：桌面入口桌宠 / 面板标题栏 / 消息头像共用
// - size：渲染尺寸（px）
// - animated：是否启用待机动画（桌宠为 true；头像/标题栏图标保持静态）
// - state：idle / thinking（流式工作态）/ complete（完成庆祝，播一次）
// - blink：一次性眨眼微表情
// 配色：全部收敛为 --fc-* CSS 变量（深底亮猫方案，亮金 + 暖白 + 深棕描边），
// 需要整体换色时只改这组变量即可。
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
          <path class="fc-ingot-body" d="M5.6 40.8 Q11.5 33.4 17.4 40.8 L15.6 42.4 L7.4 42.4 Z" stroke-width="1.2" stroke-linejoin="round"/>
          <ellipse class="fc-ingot-top" cx="11.5" cy="38.6" rx="2.8" ry="1.9" stroke-width="0.9"/>
        </g>
        <!-- 左耳 / 右耳 -->
        <path class="fc-ear" d="M11 14 L9.4 4.6 L18 9.6 Z" stroke-width="1.5" stroke-linejoin="round"/>
        <path class="fc-ear" d="M33 14 L34.6 4.6 L26 9.6 Z" stroke-width="1.5" stroke-linejoin="round"/>
        <!-- 圆脸 -->
        <circle class="fc-face" cx="22" cy="19" r="12.2" stroke-width="1.5"/>
        <!-- 暖白口鼻区 -->
        <ellipse class="fc-muzzle" cx="22" cy="23.8" rx="6.8" ry="4.8"/>
        <!-- 眼睛：常态（眨眼用） -->
        <g class="fc-eyes">
          <circle class="fc-eye" cx="17.2" cy="17.6" r="1.6"/>
          <circle class="fc-eye" cx="26.8" cy="17.6" r="1.6"/>
        </g>
        <!-- 眯眼笑（完成态显示） -->
        <g class="fc-eyes-happy">
          <path d="M15 18.2 Q17.2 15.8 19.4 18.2" stroke-width="1.5" fill="none" stroke-linecap="round"/>
          <path d="M24.6 18.2 Q26.8 15.8 29 18.2" stroke-width="1.5" fill="none" stroke-linecap="round"/>
        </g>
        <!-- 鼻 + 嘴 -->
        <circle class="fc-nose" cx="22" cy="21.6" r="1"/>
        <path class="fc-mouth" d="M19.8 24.2 Q22 26.4 24.2 24.2" stroke-width="1.3" fill="none" stroke-linecap="round"/>
        <!-- 胡须 -->
        <g class="fc-whiskers" stroke-width="0.9" stroke-linecap="round">
          <path d="M7.2 18.4 L11.4 19.2"/><path d="M7.4 21.8 L11.5 21.5"/>
          <path d="M32.6 19.2 L36.8 18.4"/><path d="M32.5 21.5 L36.6 21.8"/>
        </g>
        <!-- 颈铃 -->
        <circle class="fc-bell" cx="22" cy="31.8" r="2.1" stroke-width="1"/>
        <path class="fc-mouth" d="M22 32.6 L22 33.8" stroke-width="0.9" stroke-linecap="round"/>
        <!-- 招财爪：几何近竖直，姿态由 CSS 以肩(12.4,26)为轴旋转（静态后举 -24°） -->
        <g class="fc-paw">
          <path class="fc-paw-arm" d="M12.4 26 L11.8 16.2" stroke-width="4.8" stroke-linecap="round"/>
          <circle class="fc-paw-pad" cx="11.7" cy="14.2" r="3.2" stroke-width="1.3"/>
          <!-- 掌垫+趾垫：掌心朝向观者，「前落=招手」一眼可辨 -->
          <g class="fc-paw-pads">
            <ellipse cx="11.7" cy="14.8" rx="1.6" ry="1.2"/>
            <circle cx="10" cy="12.7" r="0.6"/>
            <circle cx="11.7" cy="12.2" r="0.6"/>
            <circle cx="13.4" cy="12.7" r="0.6"/>
          </g>
        </g>
        <!-- 怀中铜钱 -->
        <g>
          <circle class="fc-coin" cx="30.5" cy="33.6" r="4.2" stroke-width="1.2"/>
          <rect class="fc-coin-hole" x="29" y="32.1" width="3" height="3" stroke-width="0.8"/>
        </g>
      </g>
    </svg>
  </span>
</template>

<style scoped>
/* ── 配色单一来源：--fc-* 变量（亮金系，在深底圆座上对比强烈）── */
.fortune-cat {
  --fc-gold: #f7c948;      /* 主体鎏金（比旧 #f0b90b 更亮更饱和） */
  --fc-gold-hi: #ffe9a8;   /* 高光金（元宝顶/反光） */
  --fc-gold-deep: #e0a20c; /* 深金（铃铛/铜钱，拉开层次） */
  --fc-cream: #fff8e1;     /* 暖白（口鼻/掌垫/钱孔） */
  --fc-outline: #5c3d10;   /* 深棕描边（深底上依然清晰） */
  --fc-dark: #3d2a08;      /* 眼睛/眯眼笑 */
  --fc-nose: #b3722a;
  --fc-whisker: #a5822f;
  --fc-pad: #eda94f;      /* 掌垫/趾垫（掌心可读性） */
  display: inline-flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;  /* 纯视觉形象，不抢交互命中 */
}
/* ── 各部件着色（CSS 覆盖优先于表现属性，便于一键换肤）── */
.fortune-cat .fc-face, .fortune-cat .fc-ear { fill: var(--fc-gold); stroke: var(--fc-outline); }
.fortune-cat .fc-paw-arm { stroke: var(--fc-gold); }
.fortune-cat .fc-muzzle, .fortune-cat .fc-paw-pad, .fortune-cat .fc-coin-hole { fill: var(--fc-cream); }
.fortune-cat .fc-paw-pad, .fortune-cat .fc-coin-hole { stroke: var(--fc-outline); }
.fortune-cat .fc-ingot-body { fill: var(--fc-gold-deep); stroke: var(--fc-outline); }
.fortune-cat .fc-ingot-top { fill: var(--fc-gold-hi); stroke: var(--fc-outline); }
.fortune-cat .fc-bell, .fortune-cat .fc-coin { fill: var(--fc-gold-deep); stroke: var(--fc-outline); }
.fortune-cat .fc-eye { fill: var(--fc-dark); }
.fortune-cat .fc-nose { fill: var(--fc-nose); }
.fortune-cat .fc-mouth { stroke: var(--fc-outline); }
.fortune-cat .fc-eyes-happy path { stroke: var(--fc-dark); }
.fortune-cat .fc-whiskers { stroke: var(--fc-whisker); }
.fortune-cat .fc-paw-pads { fill: var(--fc-pad); }

.fc-eyes, .fc-eyes-happy, .fc-dots, .fc-ingot { transform-box: fill-box; }
.fc-eyes { transform-origin: 50% 50%; }
.fc-eyes-happy, .fc-dots { display: none; }
.fc-dots circle { fill: var(--fc-cream); opacity: 0; }

/* 动画只动 transform/opacity（GPU 友好）；仅桌宠启用（.fc--anim / 思考 / 完成） */
.fc--anim .fc-bob {
  transform-box: view-box;
  transform-origin: 22px 24px;
  animation: fc-bob 2.8s ease-in-out infinite;
}
/* 招财爪基准姿态：斜置「后举」（朝耳侧后上方 -24°，掌心朝前/朝外）；
   小尺寸静态形象（标题栏/头像）即保持该姿态 */
.fortune-cat .fc-paw {
  transform-box: view-box;
  transform-origin: 12.4px 26px;
  transform: rotate(-24deg);
}
.fc--anim .fc-paw {
  animation: fc-beckon 2.4s ease-in-out infinite;
}
@keyframes fc-bob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-1.6px); }
}
/* 招手（beckoning）：以肩为轴在「后举 -24°」与「前落 +38°」间往复——
   前落占 40%（稍快，把财招进来）、举回占 60%（缓），首尾同值循环无缝 */
@keyframes fc-beckon {
  0%, 100% { transform: rotate(-24deg); }
  40% { transform: rotate(38deg); }
  52% { transform: rotate(32deg); }
}

/* 思考/工作态：微微前倾 + 爪子摆动加快 + 头顶省略号浮动 */
.fc--thinking .fc-bob {
  transform-box: view-box;
  transform-origin: 22px 24px;
  animation: fc-tilt 1.4s ease-in-out infinite;
}
.fc--thinking .fc-paw {
  animation: fc-beckon 0.9s ease-in-out infinite;  /* 同一招手轨迹，思考态只是更快 */
}
.fc--thinking .fc-dots { display: block; }
.fc--thinking .fc-dots circle { animation: fc-dot 1.1s ease-in-out infinite; }
.fc--thinking .fc-dots circle:nth-child(2) { animation-delay: 0.18s; }
.fc--thinking .fc-dots circle:nth-child(3) { animation-delay: 0.36s; }
@keyframes fc-tilt {
  0%, 100% { transform: translateY(0) rotate(2.5deg); }
  50% { transform: translateY(-1px) rotate(-1.5deg); }
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
