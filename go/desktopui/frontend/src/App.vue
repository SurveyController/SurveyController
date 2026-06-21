<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AlertCircle } from '@lucide/vue'
import { Dialogs } from '@wailsio/runtime'
import NavRail from './components/NavRail.vue'
import WindowControls from './components/WindowControls.vue'
import DashboardView from './pages/DashboardView.vue'
import InfoView from './pages/InfoView.vue'
import LogsView from './pages/LogsView.vue'
import RuntimeView from './pages/RuntimeView.vue'
import StrategyView from './pages/StrategyView.vue'
import {
  buildDefaultConfig,
  loadAppModel,
  loadRuntimeConfig,
  previewReverseFill,
  runRuntimeConfig,
  saveRuntimeConfig,
  saveSettings,
} from './services/shell'
import { applyConfigToShell, updateAppSettingsField, updateRuntimeConfigField, type AppModel } from './services/stateMapper'
import type { RuntimeConfig, ShellState } from './types'

const shell = ref<ShellState | null>(null)
const model = ref<AppModel | null>(null)
const currentPage = ref('dashboard')
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const notice = ref('')

const config = computed(() => model.value?.config ?? null)

onMounted(async () => {
  try {
    const loaded = await loadAppModel()
    model.value = loaded
    shell.value = loaded.shell
    currentPage.value = loaded.shell.currentPage || 'dashboard'
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
})

function setConfig(next: RuntimeConfig) {
  if (!model.value || !shell.value) {
    return
  }
  model.value.config = next
  shell.value = applyConfigToShell(shell.value, model.value.settings, model.value.config, model.value.reverseFillPreview)
}

function setNotice(message: string) {
  notice.value = message
}

async function withBusy(action: () => Promise<void>) {
  busy.value = true
  error.value = ''
  try {
    await action()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    busy.value = false
  }
}

function updateConfigField(id: string, value: string | boolean) {
  if (!config.value) {
    return
  }
  setConfig(updateRuntimeConfigField(config.value, id, value))
}

function updateSettingsField(id: string, value: string | boolean) {
  if (!model.value || !shell.value) {
    return
  }
  model.value.settings = updateAppSettingsField(model.value.settings, id, value)
  shell.value = applyConfigToShell(shell.value, model.value.settings, model.value.config, model.value.reverseFillPreview)
}

function updateURL(value: string) {
  if (!config.value) {
    return
  }
  setConfig({ ...config.value, url: value })
}

async function autoConfig() {
  await withBusy(async () => {
    if (!config.value?.url) {
      throw new Error('问卷链接不能为空')
    }
    const next = await buildDefaultConfig(config.value.url)
    setConfig({
      ...config.value,
      ...next,
      target: config.value.target,
      threads: config.value.threads,
      random_ip_enabled: config.value.random_ip_enabled,
      proxy_source: config.value.proxy_source,
    })
    setNotice('问卷配置已生成')
  })
}

async function loadConfigFromDialog() {
  await withBusy(async () => {
    const path = await Dialogs.OpenFile({
      Title: '载入配置',
      CanChooseFiles: true,
      Filters: [{ DisplayName: 'JSON 配置', Pattern: '*.json' }],
    })
    if (!path || Array.isArray(path)) {
      return
    }
    const loaded = await loadRuntimeConfig(path)
    if (model.value) {
      model.value.configPath = loaded.path
    }
    setConfig(loaded.config)
    setNotice('配置已载入')
  })
}

async function saveConfigToDialog() {
  await withBusy(async () => {
    if (!config.value) {
      return
    }
    const path = await Dialogs.SaveFile({
      Title: '保存配置',
      Filename: `${config.value.survey_title || 'wjx_config'}.json`,
      Filters: [{ DisplayName: 'JSON 配置', Pattern: '*.json' }],
    })
    if (!path) {
      return
    }
    const saved = await saveRuntimeConfig(config.value, path)
    if (model.value) {
      model.value.configPath = saved.path
    }
    setConfig(saved.config)
    setNotice('配置已保存')
  })
}

async function chooseReverseFillFile() {
  await withBusy(async () => {
    const path = await Dialogs.OpenFile({
      Title: '选择反填 Excel',
      CanChooseFiles: true,
      Filters: [{ DisplayName: 'Excel 文件', Pattern: '*.xlsx;*.xlsm' }],
    })
    if (!path || Array.isArray(path) || !config.value) {
      return
    }
    setConfig({ ...config.value, reverse_fill_enabled: true, reverse_fill_source_path: path })
  })
}

async function previewReverseFillFile() {
  await withBusy(async () => {
    if (!config.value) {
      return
    }
    const preview = await previewReverseFill(config.value)
    if (!model.value || !shell.value) {
      return
    }
    model.value.reverseFillPreview = preview
    shell.value = applyConfigToShell(shell.value, model.value.settings, model.value.config, preview)
    setNotice(`已预览 ${preview.total_data_rows} 行`)
  })
}

async function saveAppSettings() {
  await withBusy(async () => {
    if (!model.value || !shell.value) {
      return
    }
    model.value.settings = await saveSettings(model.value.settings)
    shell.value = applyConfigToShell(shell.value, model.value.settings, model.value.config, model.value.reverseFillPreview)
    setNotice('设置已保存')
  })
}

async function runSurvey() {
  await withBusy(async () => {
    if (!config.value) {
      return
    }
    const state = await runRuntimeConfig(config.value)
    if (!shell.value) {
      return
    }
    shell.value = {
      ...shell.value,
      dashboard: {
        ...shell.value.dashboard,
        progressCurrent: state.result?.success ?? 0,
        progressPercent: state.result && shell.value.dashboard.progressTarget > 0
          ? Math.round((state.result.success / shell.value.dashboard.progressTarget) * 100)
          : shell.value.dashboard.progressPercent,
        statusText: state.result ? `成功 ${state.result.success}，失败 ${state.result.fail}` : '运行结束',
      },
      logLines: [
        ...(state.events ?? []).map((event) => `[${event.worker || 'core'}] ${event.message}`),
        ...shell.value.logLines,
      ].slice(0, 200),
    }
    setNotice('任务已返回结果')
  })
}
</script>

<template>
  <div class="h-screen overflow-hidden bg-[#f4f8fc] text-neutral-950 dark:bg-slate-950 dark:text-slate-100">
    <div v-if="loading" class="grid h-full place-items-center text-sm text-neutral-500">载入中</div>

    <div v-else-if="error && !shell" class="grid h-full place-items-center">
      <div class="panel flex max-w-md items-start gap-3 p-5 text-sm">
        <AlertCircle class="mt-0.5 text-red-500" :size="18" />
        <div>
          <div class="font-medium text-neutral-950 dark:text-slate-50">服务连接失败</div>
          <div class="mt-1 text-neutral-500 dark:text-slate-400">{{ error }}</div>
        </div>
      </div>
    </div>

    <div v-else-if="shell" class="flex h-full flex-col">
      <header class="app-titlebar drag-region">
        <div class="flex min-w-0 items-center gap-3">
          <div class="app-logo">
            SC
          </div>
          <div class="flex min-w-0 items-baseline gap-1.5">
            <span class="app-title truncate">{{ shell.appTitle }} v4.0.6</span>
            <span class="app-build">(84563)</span>
          </div>
          <span class="app-badge">最新</span>
        </div>
        <WindowControls />
      </header>

      <div class="flex min-h-0 flex-1">
        <NavRail
          :app-title="shell.appTitle"
          :app-version="shell.appVersion"
          :top-nav="shell.topNav"
          :bottom-nav="shell.bottomNav"
          :current-page="currentPage"
          @change="currentPage = $event"
        />

        <main class="flex min-w-0 flex-1 flex-col">
          <div v-if="error" class="mx-3 mt-2 rounded-md border border-red-100 bg-red-50 px-3 py-1.5 text-xs text-red-700 dark:border-red-950 dark:bg-red-950 dark:text-red-200">
            {{ error }}
          </div>
          <div v-if="notice" class="mx-3 mt-2 rounded-md border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs text-blue-700 dark:border-blue-950 dark:bg-blue-950 dark:text-blue-200">
            {{ notice }}
          </div>
          <DashboardView
            v-if="currentPage === 'dashboard'"
            :dashboard="shell.dashboard"
            :logs="shell.logLines"
            :busy="busy"
            @update-url="updateURL"
            @auto-config="autoConfig"
            @load-config="loadConfigFromDialog"
            @save-config="saveConfigToDialog"
            @open-runtime="currentPage = 'runtime'"
            @target-change="updateConfigField('target', String($event))"
            @threads-change="updateConfigField('threads', String($event))"
            @random-ip-change="updateConfigField('random-ip', $event)"
            @proxy-source-change="updateConfigField('proxy-source', $event)"
            @run="runSurvey"
          />
          <RuntimeView v-else-if="currentPage === 'runtime'" :groups="shell.runtimeGroups" @field-change="updateConfigField" />
          <StrategyView v-else-if="currentPage === 'strategy'" :rules="shell.strategyRules" :dimensions="shell.dimensionGroups" />
          <InfoView
            v-else-if="currentPage === 'reverse-fill'"
            title="反填"
            :reverse-fill="shell.reverseFillPlan"
            :reverse-fill-path="config?.reverse_fill_source_path"
            :busy="busy"
            @choose-reverse-fill="chooseReverseFillFile"
            @preview-reverse-fill="previewReverseFillFile"
          />
          <LogsView v-else-if="currentPage === 'logs'" :logs="shell.logLines" />
          <InfoView v-else-if="currentPage === 'community'" title="社区" :items="shell.communityItems" />
          <InfoView
            v-else-if="currentPage === 'settings'"
            title="设置"
            :settings="shell.settingsGroups"
            :busy="busy"
            @setting-change="updateSettingsField"
            @save-settings="saveAppSettings"
          />
          <InfoView v-else title="更多" :metrics="[...shell.aboutItems, ...shell.donateItems, ...shell.ipUsageItems]" />
        </main>
      </div>
    </div>
  </div>
</template>
