<script setup lang="ts">
import type { StrategyRule } from '../types'

defineProps<{
  rules: StrategyRule[]
  dimensions: string[]
}>()
</script>

<template>
  <section class="grid min-h-0 flex-1 grid-cols-[280px_minmax(0,1fr)] gap-5 overflow-hidden p-5">
    <aside class="panel overflow-hidden">
      <div class="section-title">维度</div>
      <div class="space-y-2 p-4">
        <button v-for="item in dimensions" :key="item" class="w-full rounded-md bg-slate-50 px-3 py-2 text-left text-sm text-slate-700 hover:bg-teal-50 hover:text-teal-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-teal-950">
          {{ item }}
        </button>
      </div>
    </aside>

    <div class="panel overflow-hidden">
      <div class="section-title">逻辑规则</div>
      <div class="divide-y divide-slate-100 dark:divide-slate-800">
        <div v-for="rule in rules" :key="`${rule.condition}-${rule.target}`" class="grid grid-cols-[1fr_140px_1fr] gap-4 px-5 py-4 text-sm">
          <span class="truncate text-slate-700 dark:text-slate-200">{{ rule.condition }}</span>
          <span class="rounded bg-teal-50 px-2 py-1 text-center text-teal-700 dark:bg-teal-950 dark:text-teal-200">{{ rule.action }}</span>
          <span class="truncate text-slate-500 dark:text-slate-400">{{ rule.target }}</span>
        </div>
      </div>
    </div>
  </section>
</template>
