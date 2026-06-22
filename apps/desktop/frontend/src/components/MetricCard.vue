<script setup lang="ts">
import type { PageMetric } from '../types'

defineProps<{
  metric: PageMetric
}>()
</script>

<template>
  <div class="panel p-4">
    <div class="text-xs text-slate-500 dark:text-slate-400">{{ metric.label }}</div>
    <div
      class="mt-2 text-xl font-semibold"
      :class="metric.tone === 'success' ? 'text-teal-700 dark:text-teal-300' : 'text-slate-950 dark:text-slate-50'"
    >
      {{ metric.value }}
    </div>
  </div>
</template>
