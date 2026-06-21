<script setup lang="ts">
import { FolderOpen, Play, Save, ScanLine, SlidersHorizontal } from '@lucide/vue'
import type { Component } from 'vue'
import MetricCard from '../components/MetricCard.vue'
import type { DashboardState } from '../types'

defineProps<{
  dashboard: DashboardState
  logs: string[]
}>()

const actionIcons: Record<string, Component> = {
  parse: ScanLine,
  'load-config': FolderOpen,
  'save-config': Save,
  'open-runtime': SlidersHorizontal,
}
</script>

<template>
  <section class="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_360px] gap-5 overflow-hidden p-5">
    <div class="min-w-0 space-y-5 overflow-y-auto pr-1">
      <div class="panel p-5">
        <div class="flex items-start justify-between gap-5">
          <div class="min-w-0 flex-1">
            <div class="text-sm font-medium text-teal-700 dark:text-teal-300">{{ dashboard.platformLabel }}</div>
            <h1 class="mt-2 truncate text-2xl font-semibold text-slate-950 dark:text-slate-50">{{ dashboard.surveyTitle }}</h1>
            <input class="control mt-5 w-full" :value="dashboard.surveyUrl" />
          </div>
          <button class="inline-flex h-11 items-center gap-2 rounded-md bg-teal-600 px-4 text-sm font-medium text-white shadow-sm shadow-teal-900/20 hover:bg-teal-500">
            <Play :size="17" />
            启动
          </button>
        </div>
      </div>

      <div class="grid grid-cols-4 gap-4">
        <MetricCard v-for="metric in dashboard.metrics" :key="metric.label" :metric="metric" />
      </div>

      <div class="grid grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)] gap-5">
        <div class="panel overflow-hidden">
          <div class="section-title">题目预览</div>
          <div class="divide-y divide-slate-100 dark:divide-slate-800">
            <div v-for="row in dashboard.questionRows" :key="row.index" class="grid grid-cols-[52px_88px_1fr_1.2fr] gap-3 px-4 py-3 text-sm">
              <span class="text-slate-500">#{{ row.index }}</span>
              <span class="font-medium text-slate-800 dark:text-slate-100">{{ row.type }}</span>
              <span class="truncate text-slate-600 dark:text-slate-300">{{ row.dimension }}</span>
              <span class="truncate text-slate-500 dark:text-slate-400">{{ row.strategy }}</span>
            </div>
          </div>
        </div>

        <div class="panel overflow-hidden">
          <div class="section-title">会话</div>
          <div class="space-y-3 p-4">
            <div v-for="row in dashboard.sessionRows" :key="row.thread" class="rounded-md border border-slate-100 p-3 dark:border-slate-800">
              <div class="flex items-center justify-between text-sm">
                <span class="font-medium text-slate-800 dark:text-slate-100">{{ row.thread }}</span>
                <span class="text-slate-500 dark:text-slate-400">{{ row.status }}</span>
              </div>
              <div class="mt-3 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                <div class="h-full rounded-full bg-teal-600" :style="{ width: `${row.progress}%` }"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <aside class="min-h-0 space-y-5 overflow-y-auto">
      <div class="panel p-4">
        <div class="section-title -mx-4 -mt-4">快捷操作</div>
        <div class="grid grid-cols-2 gap-3">
          <button
            v-for="action in dashboard.quickActions"
            :key="action.id"
            class="inline-flex h-11 items-center justify-center gap-2 rounded-md border border-slate-200 px-3 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-800 dark:text-slate-200 dark:hover:bg-slate-900"
            :class="{ 'border-teal-600 bg-teal-50 text-teal-700 dark:bg-teal-950 dark:text-teal-200': action.emphasis === 'primary' }"
          >
            <component :is="actionIcons[action.id] ?? ScanLine" :size="17" />
            {{ action.label }}
          </button>
        </div>
      </div>

      <div class="panel p-4">
        <div class="section-title -mx-4 -mt-4">代理状态</div>
        <div class="space-y-4">
          <div class="flex items-center justify-between">
            <span class="text-sm text-slate-500 dark:text-slate-400">随机 IP</span>
            <span class="font-medium text-teal-700 dark:text-teal-300">{{ dashboard.randomIpEnabled ? '已启用' : '关闭' }}</span>
          </div>
          <div class="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <div class="h-full rounded-full bg-teal-600" :style="{ width: `${dashboard.randomIpQuota}%` }"></div>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-slate-500 dark:text-slate-400">{{ dashboard.randomIpStatus }}</span>
            <span class="text-slate-800 dark:text-slate-100">{{ dashboard.randomIpQuotaLabel }}</span>
          </div>
        </div>
      </div>

      <div class="panel min-h-72 overflow-hidden">
        <div class="section-title">日志</div>
        <div class="space-y-2 p-4 font-mono text-xs text-slate-600 dark:text-slate-300">
          <div v-for="line in logs" :key="line" class="rounded bg-slate-50 px-3 py-2 dark:bg-slate-900">{{ line }}</div>
        </div>
      </div>
    </aside>
  </section>
</template>
