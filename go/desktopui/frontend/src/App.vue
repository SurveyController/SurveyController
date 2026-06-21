<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AlertCircle } from '@lucide/vue'
import NavRail from './components/NavRail.vue'
import WindowControls from './components/WindowControls.vue'
import DashboardView from './pages/DashboardView.vue'
import InfoView from './pages/InfoView.vue'
import LogsView from './pages/LogsView.vue'
import RuntimeView from './pages/RuntimeView.vue'
import StrategyView from './pages/StrategyView.vue'
import { loadShellState } from './services/shell'
import type { ShellState } from './types'

const shell = ref<ShellState | null>(null)
const currentPage = ref('dashboard')
const loading = ref(true)
const error = ref('')

const title = computed(() => {
  const nav = [...(shell.value?.topNav ?? []), ...(shell.value?.bottomNav ?? [])]
  return nav.find((item) => item.id === currentPage.value)?.label ?? '概览'
})

onMounted(async () => {
  try {
    const state = await loadShellState()
    shell.value = state
    currentPage.value = state.currentPage || 'dashboard'
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="h-screen overflow-hidden bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
    <div v-if="loading" class="grid h-full place-items-center text-sm text-slate-500">载入中</div>

    <div v-else-if="error" class="grid h-full place-items-center">
      <div class="panel flex max-w-md items-start gap-3 p-5 text-sm">
        <AlertCircle class="mt-0.5 text-red-500" :size="18" />
        <div>
          <div class="font-medium text-slate-950 dark:text-slate-50">服务连接失败</div>
          <div class="mt-1 text-slate-500 dark:text-slate-400">{{ error }}</div>
        </div>
      </div>
    </div>

    <div v-else-if="shell" class="flex h-full">
      <NavRail
        :app-title="shell.appTitle"
        :app-version="shell.appVersion"
        :top-nav="shell.topNav"
        :bottom-nav="shell.bottomNav"
        :current-page="currentPage"
        @change="currentPage = $event"
      />

      <main class="flex min-w-0 flex-1 flex-col">
        <header class="drag-region flex h-11 shrink-0 items-center justify-between border-b border-slate-200 bg-white/70 pl-5 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/70">
          <div class="text-sm font-medium text-slate-700 dark:text-slate-200">{{ title }}</div>
          <WindowControls />
        </header>

        <DashboardView v-if="currentPage === 'dashboard'" :dashboard="shell.dashboard" :logs="shell.logLines" />
        <RuntimeView v-else-if="currentPage === 'runtime'" :groups="shell.runtimeGroups" />
        <StrategyView v-else-if="currentPage === 'strategy'" :rules="shell.strategyRules" :dimensions="shell.dimensionGroups" />
        <InfoView v-else-if="currentPage === 'reverse-fill'" title="反填" :reverse-fill="shell.reverseFillPlan" />
        <LogsView v-else-if="currentPage === 'logs'" :logs="shell.logLines" />
        <InfoView v-else-if="currentPage === 'community'" title="社区" :items="shell.communityItems" />
        <InfoView v-else-if="currentPage === 'settings'" title="设置" :settings="shell.settingsGroups" />
        <InfoView v-else title="更多" :metrics="[...shell.aboutItems, ...shell.donateItems, ...shell.ipUsageItems]" />
      </main>
    </div>
  </div>
</template>
