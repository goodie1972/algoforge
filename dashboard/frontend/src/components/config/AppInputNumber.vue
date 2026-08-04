<script setup lang="ts">
import { ref, watch } from 'vue'
import { NInput } from 'naive-ui'
import { IconChevronUp, IconChevronDown } from '@tabler/icons-vue'

const props = defineProps<{
  modelValue: number | null
  min?: number
  max?: number
  step?: number
  disabled?: boolean
  size?: 'tiny' | 'small' | 'medium' | 'large'
  placeholder?: string
  precision?: number
}>()

const emit = defineEmits<{
  'update:modelValue': [value: number | null]
  'update:value': [value: number | null]
}>()

// 显示用字符串（保证 n-input 始终有值显示）
const displayVal = ref('')

// 从 modelValue 同步到 displayVal
watch(() => props.modelValue, (v) => {
  displayVal.value = v != null ? String(v) : ''
}, { immediate: true })

// 从显示值同步回 modelValue
function onInput(v: string | null) {
  const raw = (v ?? '').trim()
  displayVal.value = raw
  if (raw === '') {
    emit('update:modelValue', null)
    emit('update:value', null)
    return
  }
  const n = parseFloat(raw)
  if (!isNaN(n)) {
    const min = props.min ?? -Infinity
    const max = props.max ?? Infinity
    const clamped = Math.max(min, Math.min(max, n))
    let final = clamped
    if (props.precision != null) {
      final = parseFloat(clamped.toFixed(props.precision))
    }
    emit('update:modelValue', final)
    emit('update:value', final)
  }
}

function clamp(v: number): number {
  const min = props.min ?? -Infinity
  const max = props.max ?? Infinity
  return Math.max(min, Math.min(max, v))
}

function inc() {
  const step = props.step ?? 1
  const cur = props.modelValue ?? 0
  const next = clamp(cur + step)
  let final = next
  if (props.precision != null) {
    final = parseFloat(next.toFixed(props.precision))
  }
  displayVal.value = String(final)
  emit('update:modelValue', final)
  emit('update:value', final)
}

function dec() {
  const step = props.step ?? 1
  const cur = props.modelValue ?? 0
  const next = clamp(cur - step)
  let final = next
  if (props.precision != null) {
    final = parseFloat(next.toFixed(props.precision))
  }
  displayVal.value = String(final)
  emit('update:modelValue', final)
  emit('update:value', final)
}

function getBtnSize(): number {
  if (props.size === 'tiny') return 12
  if (props.size === 'small') return 14
  return 16
}
</script>

<template>
  <div class="custom-input-number" :class="[size ?? 'tiny']">
    <button class="num-btn num-up" :disabled="disabled" @click="inc" tabindex="-1">
      <IconChevronUp :size="getBtnSize()" />
    </button>
    <n-input
      v-model:value="displayVal"
      :placeholder="placeholder"
      :disabled="disabled"
      :size="size"
      class="num-input"
      @update:value="onInput"
    />
    <button class="num-btn num-down" :disabled="disabled" @click="dec" tabindex="-1">
      <IconChevronDown :size="getBtnSize()" />
    </button>
  </div>
</template>

<style scoped>
.custom-input-number {
  display: inline-flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0;
}
.num-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #3b3b3b;
  background: #2a2a2a;
  color: #ccc;
  cursor: pointer;
  padding: 0;
  line-height: 1;
  transition: background 0.15s, color 0.15s;
  border-radius: 0;
  user-select: none;
}
.num-btn:hover:not(:disabled) {
  background: #3a3a3a;
  color: #f0b90b;
}
.num-btn:active:not(:disabled) {
  background: #4a4a4a;
}
.num-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.num-up {
  border-bottom: none;
  border-radius: 3px 3px 0 0;
}
.num-down {
  border-top: none;
  border-radius: 0 0 3px 3px;
}
.num-input {
  --n-border: 1px solid #3b3b3b !important;
  --n-border-hover: 1px solid #f0b90b !important;
  --n-border-focus: 1px solid #f0b90b !important;
}
.num-input :deep(.n-input) {
  border-radius: 0 !important;
}
/* tiny 尺寸 */
.custom-input-number.tiny .num-btn {
  height: 12px;
  min-height: 12px;
}
.custom-input-number.small .num-btn {
  height: 14px;
  min-height: 14px;
}
.custom-input-number.medium .num-btn {
  height: 16px;
  min-height: 16px;
}
.custom-input-number.large .num-btn {
  height: 18px;
  min-height: 18px;
}
</style>