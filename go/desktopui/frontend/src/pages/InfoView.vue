<script setup lang="ts">
import type { PageMetric, ReverseFillRow, SettingsGroup } from '../types'
import SettingField from '../components/SettingField.vue'

defineProps<{
  title: string
  items?: string[]
  metrics?: PageMetric[]
  reverseFill?: ReverseFillRow[]
  settings?: SettingsGroup[]
}>()
</script>

<template>
  <section class="min-h-0 flex-1 overflow-y-auto p-5">
    <div class="mx-auto max-w-4xl space-y-5">
      <div class="panel overflow-hidden">
        <div class="section-title">{{ title }}</div>

        <div v-if="items?.length" class="space-y-2 p-4">
          <div v-for="item in items" :key="item" class="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:bg-slate-900 dark:text-slate-200">
            {{ item }}
          </div>
        </div>

        <div v-else-if="metrics?.length" class="grid grid-cols-2 gap-4 p-4">
          <div v-for="metric in metrics" :key="metric.label" class="rounded-md bg-slate-50 p-4 dark:bg-slate-900">
            <div class="text-xs text-slate-500 dark:text-slate-400">{{ metric.label }}</div>
            <div class="mt-2 font-medium text-slate-900 dark:text-slate-100">{{ metric.value }}</div>
          </div>
        </div>

        <div v-else-if="reverseFill?.length" class="divide-y divide-slate-100 dark:divide-slate-800">
          <div v-for="row in reverseFill" :key="`${row.question}-${row.column}`" class="grid grid-cols-3 gap-4 px-5 py-4 text-sm">
            <span>{{ row.question }}</span>
            <span class="text-slate-500 dark:text-slate-400">{{ row.column }}</span>
            <span class="text-teal-700 dark:text-teal-300">{{ row.state }}</span>
          </div>
        </div>
      </div>

      <div v-for="group in settings" :key="group.title" class="panel overflow-hidden">
        <div class="section-title">{{ group.title }}</div>
        <div class="px-4">
          <SettingField v-for="field in group.fields" :key="field.id" :field="field" />
        </div>
      </div>
    </div>
  </section>
</template>
