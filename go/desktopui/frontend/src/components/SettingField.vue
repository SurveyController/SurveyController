<script setup lang="ts">
import type { SettingField } from '../types'

defineProps<{
  field: SettingField
}>()
</script>

<template>
  <div class="flex items-center justify-between gap-5 border-b border-slate-100 py-4 last:border-b-0 dark:border-slate-800">
    <div class="min-w-0">
      <div class="text-sm font-medium text-slate-900 dark:text-slate-100">{{ field.label }}</div>
      <div class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ field.description }}</div>
    </div>

    <label v-if="field.kind === 'toggle'" class="relative inline-flex cursor-pointer items-center">
      <input class="peer sr-only" type="checkbox" :checked="field.value === 'true'" />
      <span class="h-6 w-11 rounded-full bg-slate-300 transition peer-checked:bg-teal-600 dark:bg-slate-700"></span>
      <span class="absolute left-1 h-4 w-4 rounded-full bg-white transition peer-checked:translate-x-5"></span>
    </label>

    <select v-else-if="field.kind === 'select'" class="control w-36">
      <option>{{ field.value }}</option>
      <option v-for="option in field.options?.filter((item) => item !== field.value)" :key="option">
        {{ option }}
      </option>
    </select>

    <input v-else-if="field.kind === 'number'" class="control w-28" :value="field.value" />

    <div v-else class="min-w-32 rounded bg-slate-100 px-3 py-2 text-right text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200">
      {{ field.value }}
    </div>
  </div>
</template>
