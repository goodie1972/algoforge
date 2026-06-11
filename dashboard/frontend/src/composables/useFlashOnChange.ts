/**
 * 数值变化时触发背景闪烁动画，600ms 后自动熄灭。
 * 用法: const flash = useFlashOnChange(() => store.bid)
 *       <span :class="{ 'flash-num': flash }">{{ store.bid }}</span>
 */
import { ref, watch } from 'vue'

export function useFlashOnChange(
  getter: () => number,
  duration = 600,
  threshold = 0.01,
) {
  const flash = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null

  watch(getter, (n, o) => {
    if (o === undefined || Math.abs(n - o) < threshold) return
    flash.value = true
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => { flash.value = false }, duration)
  })

  return flash
}
