<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { IconChevronUp, IconChevronDown } from '@tabler/icons-vue'

const props = defineProps<{
  value: number | null
  min?: number
  max?: number
  step?: number
  disabled?: boolean
  size?: 'tiny' | 'small' | 'medium' | 'large'
  placeholder?: string
  precision?: number
}>()

const emit = defineEmits<{
  'update:value': [value: number | null]
}>()

const displayVal = ref('')

onMounted(() => {
  displayVal.value = props.value != null ? String(props.value) : ''
})

function clamp(v: number): number {
  const min = props.min ?? -Infinity
  const max = props.max ?? Infinity
  return Math.max(min, Math.min(max, v))
}

function emitValue(n: number) {
  let final = n
  if (props.precision != null) {
    final = parseFloat(n.toFixed(props.precision))
  }
  displayVal.value = String(final)
  emit('update:value', final)
}

function inc() {
  const step = props.step ?? 1
  const cur = props.value ?? 0
  emitValue(clamp(cur + step))
}

function dec() {
  const step = props.step ?? 1
  const cur = props.value ?? 0
  emitValue(clamp(cur - step))
}

function onInput(e: Event) {
  const raw = (e.target as HTMLInputElement).value.trim()
  displayVal.value = raw
  if (raw === '') {
    emit('update:value', null)
    return
  }
  const n = parseFloat(raw)
  if (!isNaN(n)) {
    emitValue(clamp(n))
  }
}

function getBtnSize(): number {
  if (props.size === 'tiny') return 12
  if (props.size === 'small') return 14
  return 16
}
</script>

<template>
  <div class="cnum" :class="[size ?? 'tiny']">
    <button class="cnum-btn cnum-up" :disabled="disabled" @click="inc" tabindex="-1">
      <IconChevronUp :size="getBtnSize()" />
    </button>
    <input
      class="cnum-input"
      type="text"
      :value="displayVal"
      :placeholder="placeholder"
      :disabled="disabled"
      @input="onInput"
    />
    <button class="cnum-btn cnum-down" :disabled="disabled" @click="dec" tabindex="-1">
      <IconChevronDown :size="getBtnSize()" />
    </button>
  </div>
</template>

<style scoped>
.cnum {
  display: inline-flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0;
}
.cnum-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #3b3b3b;
  background: #2a2a2a;
  color: #ccc;
  cursor: pointer;
  padding: 0;
  line-height: 1;
  transition: background 0.12s, color 0.12s;
  user-select: none;
}
.cnum-btn:hover:not(:disabled) {
  background: #3a3a3a;
  color: #f0b90b;
}
.cnum-btn:active:not(:disabled) {
  background: #4a4a4a;
}
.cnum-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.cnum-up {
  border-bottom: none;
  border-radius: 3px 3px 0 0;
}
.cnum-down {
  border-top: none;
  border-radius: 0 0 3px 3px;
}
.cnum-input {
  display: block;
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #3b3b3b;
  border-top: none;
  border-bottom: none;
  background: #1a1d23;
  color: #e6edf3;
  text-align: center;
  font-size: inherit;
  font-family: inherit;
  outline: none;
  padding: 0 2px;
  min-width: 0;
}
.cnum-input:focus {
  border-color: #f0b90b;
  background: #22262e;
}
.cnum-input:disabled {
  opacity: 0.5;
}
.cnum-input::placeholder {
  color: #555;
}
.cnum.tiny .cnum-btn { height: 12px; }
.cnum.tiny .cnum-input { height: 20px; font-size: 10px; }
.cnum.small .cnum-btn { height: 14px; }
.cnum.small .cnum-input { height: 24px; font-size: 11px; }
.cnum.medium .cnum-btn { height: 16px; }
.cnum.medium .cnum-input { height: 28px; font-size: 12px; }
.cnum.large .cnum-btn { height: 18px; }
.cnum.large .cnum-input { height: 32px; font-size: 13px; }
</style>