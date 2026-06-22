<script setup lang="ts">
import {
  CircleEllipsis,
  CircleHelp,
  FileText,
  GitBranch,
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
  settings: SlidersHorizontal,
  flow: GitBranch,
  refresh: RefreshCcw,
  document: CircleHelp,
  chat: MessageCircle,
  sliders: Settings,
  grid: CircleEllipsis,
}

function iconFor(item: NavItem): Component {
  return icons[item.icon] ?? FileText
}
</script>

<template>
  <aside class="side-nav">
    <nav class="flex flex-1 flex-col justify-between px-1.5 py-1.5">
      <div class="space-y-0.5">
        <button
          v-for="item in topNav"
          :key="item.id"
          class="side-nav-item"
          :class="{ 'side-nav-active': currentPage === item.id }"
          @click="emit('change', item.id)"
        >
          <component :is="iconFor(item)" class="side-nav-icon" :stroke-width="2" />
          <span class="side-nav-label">{{ item.label }}</span>
          <span v-if="item.badge" class="absolute right-0.5 top-0.5 rounded-full bg-amber-400 px-1.5 py-0.5 text-[10px] text-white">
            {{ item.badge }}
          </span>
        </button>
      </div>

      <div class="space-y-0.5">
        <button
          v-for="item in bottomNav"
          :key="item.id"
          class="side-nav-item"
          :class="{ 'side-nav-active': currentPage === item.id }"
          @click="emit('change', item.id)"
        >
          <component :is="iconFor(item)" class="side-nav-icon" :stroke-width="2" />
          <span class="side-nav-label">{{ item.label }}</span>
        </button>
      </div>
    </nav>
  </aside>
</template>
