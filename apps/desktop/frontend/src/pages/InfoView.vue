<script setup lang="ts">
import type { PageMetric, ReverseFillRow, SettingsGroup } from '../types'
import SettingField from '../components/SettingField.vue'

defineProps<{
  title: string
  items?: string[]
  metrics?: PageMetric[]
  reverseFill?: ReverseFillRow[]
  settings?: SettingsGroup[]
  reverseFillEnabled?: boolean
  reverseFillPath?: string
  busy?: boolean
}>()

const emit = defineEmits<{
  settingChange: [id: string, value: string | boolean]
  chooseReverseFill: []
  previewReverseFill: []
  saveSettings: []
}>()
</script>

<template>
  <section class="min-h-0 flex-1 overflow-y-auto p-3">
    <div class="mx-auto max-w-4xl space-y-3">
      <div class="panel overflow-hidden">
        <div class="section-title">{{ title }}</div>

        <div v-if="reverseFill" class="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3 text-xs dark:border-slate-800">
          <button class="runtime-open-button" @click="emit('chooseReverseFill')">选择 Excel</button>
          <button class="runtime-open-button" :disabled="busy || !reverseFillPath" @click="emit('previewReverseFill')">预览反填</button>
          <span class="min-w-0 flex-1 truncate text-slate-500 dark:text-slate-400">{{ reverseFillPath || '未选择文件' }}</span>
        </div>

        <div v-if="items?.length" class="space-y-1.5 p-3">
          <div v-for="item in items" :key="item" class="rounded-md bg-slate-50 px-2.5 py-1.5 text-xs text-slate-700 dark:bg-slate-900 dark:text-slate-200">
            {{ item }}
          </div>
        </div>

        <div v-else-if="metrics?.length" class="grid grid-cols-2 gap-3 p-3">
          <div v-for="metric in metrics" :key="metric.label" class="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
            <div class="text-xs text-slate-500 dark:text-slate-400">{{ metric.label }}</div>
            <div class="mt-1.5 text-sm font-medium text-slate-900 dark:text-slate-100">{{ metric.value }}</div>
          </div>
        </div>

        <div v-else-if="reverseFill?.length" class="divide-y divide-slate-100 dark:divide-slate-800">
          <div v-for="row in reverseFill" :key="`${row.question}-${row.column}`" class="grid grid-cols-3 gap-3 px-3 py-2.5 text-xs">
            <span>{{ row.question }}</span>
            <span class="text-slate-500 dark:text-slate-400">{{ row.column }}</span>
            <span class="text-teal-700 dark:text-teal-300">{{ row.state }}</span>
          </div>
        </div>
      </div>

      <div v-for="group in settings" :key="group.title" class="panel overflow-hidden">
        <div class="section-title">{{ group.title }}</div>
        <div class="px-3">
          <SettingField
            v-for="field in group.fields"
            :key="field.id"
            :field="field"
            @change="(id, value) => emit('settingChange', id, value)"
          />
        </div>
      </div>

      <div v-if="settings?.length" class="flex justify-end">
        <button class="runtime-open-button" :disabled="busy" @click="emit('saveSettings')">保存设置</button>
      </div>
    </div>
  </section>
</template>
