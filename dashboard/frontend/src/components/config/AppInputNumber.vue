<script setup lang="ts">
import { computed } from 'vue'
import { NInputNumber } from 'naive-ui'
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
}>()

const local = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})
</script>

<template>
  <n-input-number
    v-model:value="local"
    :min="min"
    :max="max"
    :step="step"
    :disabled="disabled"
    :size="size"
    :placeholder="placeholder"
    :precision="precision"
    :show-button="true"
    button-placement="right"
  >
    <template #minus-icon>
      <IconChevronDown :size="14" />
    </template>
    <template #add-icon>
      <IconChevronUp :size="14" />
    </template>
  </n-input-number>
</template>
