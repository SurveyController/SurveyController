<script setup lang="ts">
import {
  FileText,
  Gauge,
  GitBranch,
  Grid2X2,
  Home,
  MessageCircle,
  RefreshCcw,
  Settings,
  SlidersHorizontal,
} from '@lucide/vue'
import type { Component } from 'vue'
import type { NavItem } from '../types'

defineProps<{
  appTitle: string
  appVersion: string
  topNav: NavItem[]
  bottomNav: NavItem[]
  currentPage: string
}>()

const emit = defineEmits<{
  change: [page: string]
}>()

const icons: Record<string, Component> = {
  home: Home,
  settings: Gauge,
  flow: GitBranch,
  refresh: RefreshCcw,
  document: FileText,
  chat: MessageCircle,
  sliders: SlidersHorizontal,
  grid: Grid2X2,
}

function iconFor(item: NavItem): Component {
  return icons[item.icon] ?? Settings
}
</script>

<template>
  <aside class="flex h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white/78 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/78">
    <div class="drag-region flex h-16 items-center gap-3 px-5">
      <div class="grid h-9 w-9 place-items-center rounded-md bg-teal-600 text-sm font-semibold text-white shadow-sm shadow-teal-900/20">
        SC
      </div>
      <div class="min-w-0">
        <div class="truncate text-sm font-semibold text-slate-950 dark:text-slate-50">{{ appTitle }}</div>
        <div class="truncate text-xs text-slate-500 dark:text-slate-400">{{ appVersion }}</div>
      </div>
    </div>

    <nav class="flex flex-1 flex-col justify-between px-3 pb-4 pt-2">
      <div class="space-y-1">
        <button
          v-for="item in topNav"
          :key="item.id"
          class="nav-item"
          :class="{ 'nav-item-active': currentPage === item.id }"
          @click="emit('change', item.id)"
        >
          <component :is="iconFor(item)" :size="18" />
          <span class="truncate">{{ item.label }}</span>
          <span v-if="item.badge" class="ml-auto rounded bg-teal-50 px-1.5 py-0.5 text-[11px] text-teal-700 dark:bg-teal-950 dark:text-teal-200">
            {{ item.badge }}
          </span>
        </button>
      </div>

      <div class="space-y-1">
        <button
          v-for="item in bottomNav"
          :key="item.id"
          class="nav-item"
          :class="{ 'nav-item-active': currentPage === item.id }"
          @click="emit('change', item.id)"
        >
          <component :is="iconFor(item)" :size="18" />
          <span class="truncate">{{ item.label }}</span>
        </button>
      </div>
    </nav>
  </aside>
</template>
