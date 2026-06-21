<script setup lang="ts">
import type { SettingField } from '../types'

const props = defineProps<{
  field: SettingField
}>()

const emit = defineEmits<{
  change: [id: string, value: string | boolean]
}>()

function onInput(event: Event) {
  const target = event.target as HTMLInputElement | HTMLSelectElement
  emit('change', props.field.id, target.value)
}

function onToggle(event: Event) {
  const target = event.target as HTMLInputElement
  emit('change', props.field.id, target.checked)
}
</script>

<template>
  <div class="flex items-center justify-between gap-3 border-b border-slate-100 py-2.5 last:border-b-0 dark:border-slate-800">
    <div class="min-w-0">
      <div class="text-xs font-medium text-slate-900 dark:text-slate-100">{{ field.label }}</div>
      <div class="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">{{ field.description }}</div>
    </div>

    <label v-if="field.kind === 'toggle'" class="relative inline-flex cursor-pointer items-center">
      <input class="peer sr-only" type="checkbox" :checked="field.value === 'true'" @change="onToggle" />
      <span class="h-5 w-9 rounded-full bg-slate-300 transition peer-checked:bg-teal-600 dark:bg-slate-700"></span>
      <span class="absolute left-0.5 h-4 w-4 rounded-full bg-white transition peer-checked:translate-x-4"></span>
    </label>

    <select v-else-if="field.kind === 'select'" class="control w-32" :value="field.value" @change="onInput">
      <option>{{ field.value }}</option>
      <option v-for="option in field.options?.filter((item) => item !== field.value)" :key="option">
        {{ option }}
      </option>
    </select>

    <input v-else-if="field.kind === 'number'" class="control w-24" type="number" :value="field.value" @change="onInput" />

    <input v-else-if="field.kind === 'text'" class="control w-52" :value="field.value" @change="onInput" />

    <div v-else class="min-w-28 rounded bg-slate-100 px-2.5 py-1.5 text-right text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200">
      {{ field.value }}
    </div>
  </div>
</template>
