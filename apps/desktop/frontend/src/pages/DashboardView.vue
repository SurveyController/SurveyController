<script setup lang="ts">
import {
  Brush,
  ChevronDown,
  ChevronUp,
  FilePlus2,
  List,
  Play,
  QrCode,
  Save,
  SlidersHorizontal,
  Square,
  Trash2,
} from '@lucide/vue'
import type { DashboardState } from '../types'

defineProps<{
  dashboard: DashboardState
  logs: string[]
  busy?: boolean
}>()

const emit = defineEmits<{
  updateUrl: [value: string]
  autoConfig: []
  loadConfig: []
  saveConfig: []
  openRuntime: []
  targetChange: [value: number]
  threadsChange: [value: number]
  randomIpChange: [value: boolean]
  proxySourceChange: [value: string]
  run: []
  cancelRun: []
}>()

function emitTarget(event: Event) {
  const target = event.target as HTMLInputElement
  emit('targetChange', Number(target.value))
}

function emitThreads(event: Event) {
  const target = event.target as HTMLInputElement
  emit('threadsChange', Number(target.value))
}

function emitURL(event: Event) {
  const target = event.target as HTMLInputElement
  emit('updateUrl', target.value)
}
</script>

<template>
  <section class="dashboard-root">
    <div class="dashboard-scroll min-h-0 flex-1 overflow-y-auto pr-1">
      <div class="work-panel survey-entry-panel">
        <div class="survey-entry-layout">
          <button class="qr-button">
            <QrCode class="qr-icon" />
          </button>

          <div class="min-w-0 flex-1">
            <div class="survey-toolbar">
              <input
                class="survey-url-input"
                placeholder="在此拖入/粘贴问卷二维码图片或输入问卷链接"
                :value="dashboard.surveyUrl"
                @input="emitURL"
              />
              <button class="toolbar-command" @click="emit('loadConfig')">
                <List class="toolbar-icon" />
                配置列表
              </button>
              <button class="toolbar-command" @click="emit('loadConfig')">
                <FilePlus2 class="toolbar-icon" />
                载入配置
              </button>
              <button class="toolbar-command" @click="emit('saveConfig')">
                <Save class="toolbar-icon" />
                保存配置
              </button>
            </div>

            <button class="auto-config-button" :disabled="busy || !dashboard.surveyUrl" @click="emit('autoConfig')">
              <Play class="auto-config-icon" />
              自动配置问卷
            </button>
          </div>
        </div>
      </div>

      <div class="work-panel quick-panel">
        <h1 class="quick-title">快捷设置</h1>

        <div class="quick-layout">
          <div class="space-y-3">
            <div class="settings-line settings-line-primary">
              <label class="setting-label">目标份数:</label>
              <div class="number-stepper">
                <input
                  class="number-stepper-input"
                  type="number"
                  min="1"
                  :value="dashboard.targetCount"
                  @change="emitTarget"
                />
                <div class="ml-auto flex h-full items-center divide-x divide-slate-200 border-l border-slate-200 dark:divide-slate-700 dark:border-slate-700">
                  <button class="stepper-button"><ChevronUp class="stepper-icon" /></button>
                  <button class="stepper-button"><ChevronDown class="stepper-icon" /></button>
                </div>
              </div>

              <label class="setting-label">并发数:</label>
              <input
                class="thread-slider"
                type="range"
                min="1"
                max="32"
                :value="Math.max(1, dashboard.threadCount)"
                @input="emitThreads"
              />
              <span class="thread-value">{{ Math.max(1, Math.min(dashboard.threadCount, 32)) }}</span>
            </div>

            <div class="settings-line">
              <label class="setting-label">随机IP:</label>
              <span class="setting-value">{{ dashboard.randomIpEnabled ? '开' : '关' }}</span>
              <button
                class="toggle-shell"
                :class="{ 'toggle-shell-on': dashboard.randomIpEnabled }"
                @click="emit('randomIpChange', !dashboard.randomIpEnabled)"
              >
                <span class="toggle-dot"></span>
              </button>
            </div>

            <div class="settings-line">
              <label class="setting-label">代理源:</label>
              <select class="select-button fluent-select" :value="dashboard.proxySource" @change="(event) => emit('proxySourceChange', (event.target as HTMLSelectElement).value)">
                <option>默认</option>
                <option>限时福利</option>
                <option>自定义</option>
              </select>
            </div>

            <div class="runtime-card">
              <div class="runtime-icon-box">
                <SlidersHorizontal class="runtime-icon" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="runtime-title">运行参数</div>
                <div class="runtime-desc">更多设置请前往“运行参数”页仔细调整</div>
              </div>
              <button class="runtime-open-button" @click="emit('openRuntime')">
                打开
              </button>
            </div>
          </div>

          <aside v-if="dashboard.randomIpEnabled" class="quota-card">
            <div class="quota-title">剩余随机IP额度</div>
            <div class="quota-status">
              <span class="quota-dot"></span>
              {{ dashboard.randomIpStatus }}
            </div>
            <div class="quota-ring">
              <span class="quota-value">{{ dashboard.randomIpQuotaLabel }}</span>
            </div>
            <div class="quota-meta">
              可用 {{ dashboard.proxyAvailable ?? 0 }} / 占用 {{ dashboard.proxyInUse ?? 0 }}
            </div>
            <button class="quota-button">
              <span class="text-orange-600">LD</span>
              额度兑换
            </button>
          </aside>
        </div>
      </div>

      <div class="dashboard-tabs">
        <button class="tab-button tab-active">题目清单</button>
        <button class="tab-button">会话进度</button>
      </div>

      <div class="work-panel question-panel">
        <div class="flex items-center justify-between">
          <h2 class="question-title">已配置的题目</h2>
          <span class="question-count">{{ dashboard.questionRows.length }} 题</span>
        </div>

        <div class="table-actions">
          <button class="table-action"><FilePlus2 class="table-action-icon" />新增题目</button>
          <button class="table-action"><Brush class="table-action-icon" />编辑选中</button>
          <button class="table-action"><Trash2 class="table-action-icon" />删除选中</button>
          <button class="table-action"><Brush class="table-action-icon" />清空所有已配置题目</button>
        </div>

        <div class="question-table">
          <div class="question-table-row question-table-head">
            <div class="table-head">序号</div>
            <div class="table-head">类型</div>
            <div class="table-head">维度</div>
            <div class="table-head">策略</div>
          </div>
          <div
            v-for="row in dashboard.questionRows"
            :key="row.index"
            class="question-table-row question-table-body"
          >
            <div class="table-cell">{{ row.index }}</div>
            <div class="table-cell">{{ row.type }}</div>
            <div class="table-cell">{{ row.dimension }}</div>
            <div class="table-cell">{{ row.strategy }}</div>
          </div>
        </div>
      </div>

      <div v-if="dashboard.sessionRows.length" class="work-panel session-panel">
        <div class="flex items-center justify-between">
          <h2 class="question-title">会话进度</h2>
          <span class="question-count">{{ dashboard.sessionRows.length }} 路</span>
        </div>
        <div class="session-grid">
          <div v-for="row in dashboard.sessionRows" :key="row.thread" class="session-row">
            <div class="min-w-0">
              <div class="session-name">{{ row.thread }}</div>
              <div class="session-status">{{ row.status }}</div>
            </div>
            <div class="session-progress">
              <span :style="{ width: `${row.progress}%` }"></span>
            </div>
            <div class="session-percent">{{ row.progress }}%</div>
          </div>
        </div>
      </div>
    </div>

    <footer class="run-footer">
      <div class="run-status">{{ dashboard.statusText }}</div>
      <div class="run-progress-track"></div>
      <div class="run-progress-value">{{ dashboard.progressPercent }}%</div>
      <button class="run-button-primary" :disabled="busy || !dashboard.surveyUrl" @click="emit('run')">
        <Play class="auto-config-icon" />
        开始执行
      </button>
      <button class="run-button-secondary" :disabled="!busy" @click="emit('cancelRun')">
        <Square class="auto-config-icon" />
        停止
      </button>
    </footer>
  </section>
</template>
