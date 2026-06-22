import type { AppSettings, ProxyStatus, ReverseFillPreview, RunTaskState, RuntimeConfig, ShellState, SurveyCoreState } from '../types'
import {
  BuildDefaultConfig,
  CancelRun,
  GetProxyStatus,
  GetRunTaskState,
  GetAppSettings,
  GetShellState,
  LoadConfig,
  PreviewReverseFill,
  RunSurvey,
  SaveAppSettings,
  SaveConfig,
  StartRun,
} from '../../bindings/github.com/hungrym0/SurveyController/apps/desktop/appservice'
import { buildAppModel, type AppModel } from './stateMapper'

export async function loadShellState(): Promise<ShellState> {
  try {
    return (await GetShellState()) as ShellState
  } catch (err) {
    if (canUsePreviewState()) {
      return previewShellState()
    }
    throw err
  }
}

export async function loadAppModel(): Promise<AppModel> {
  try {
    const [shell, settings] = await Promise.all([
      GetShellState() as Promise<ShellState>,
      GetAppSettings() as Promise<AppSettings>,
    ])
    const loaded = await LoadConfig({ path: '' }).catch(() => null)
    return buildAppModel(shell, settings, (loaded?.config ?? null) as RuntimeConfig | null)
  } catch (err) {
    if (canUsePreviewState()) {
      return buildAppModel(previewShellState(), previewAppSettings(), null)
    }
    throw err
  }
}

export async function buildDefaultConfig(url: string): Promise<RuntimeConfig> {
  const state = await BuildDefaultConfig({ url }) as SurveyCoreState
  if (!state.config) {
    throw new Error('自动配置没有返回运行配置')
  }
  return state.config
}

export async function loadRuntimeConfig(path: string): Promise<{ path: string; config: RuntimeConfig }> {
  const state = await LoadConfig({ path }) as { path: string; config?: RuntimeConfig | null }
  if (!state.config) {
    throw new Error('配置文件没有运行配置')
  }
  return { path: state.path, config: state.config }
}

export async function saveRuntimeConfig(config: RuntimeConfig, path = ''): Promise<{ path: string; config: RuntimeConfig }> {
  const state = await SaveConfig({ path, config: config as any }) as { path: string; config?: RuntimeConfig | null }
  return { path: state.path, config: state.config ?? config }
}

export async function saveSettings(settings: AppSettings): Promise<AppSettings> {
  return await SaveAppSettings({ settings: settings as any }) as AppSettings
}

export async function previewReverseFill(config: RuntimeConfig): Promise<ReverseFillPreview> {
  return await PreviewReverseFill({
    path: config.reverse_fill_source_path ?? '',
    format: config.reverse_fill_format ?? 'auto',
    startRow: config.reverse_fill_start_row ?? 1,
    questions: (config.questions_info ?? []) as any,
  }) as ReverseFillPreview
}

export async function runRuntimeConfig(config: RuntimeConfig): Promise<SurveyCoreState> {
  return await RunSurvey({ config: config as any }) as SurveyCoreState
}

export async function startRuntimeConfig(config: RuntimeConfig): Promise<RunTaskState> {
  return await StartRun({ config: config as any }) as RunTaskState
}

export async function loadRunTaskState(): Promise<RunTaskState> {
  return await GetRunTaskState() as RunTaskState
}

export async function cancelRuntimeConfig(): Promise<RunTaskState> {
  return await CancelRun() as RunTaskState
}

export async function loadProxyStatus(): Promise<ProxyStatus> {
  return await GetProxyStatus() as ProxyStatus
}

function canUsePreviewState(): boolean {
  return import.meta.env.DEV && !hasNativeWailsBridge()
}

function hasNativeWailsBridge(): boolean {
  const win = globalThis as typeof globalThis & {
    chrome?: { webview?: { postMessage?: unknown } }
    webkit?: { messageHandlers?: { external?: { postMessage?: unknown } } }
    wails?: { invoke?: unknown }
  }
  return Boolean(
    win.chrome?.webview?.postMessage ||
    win.webkit?.messageHandlers?.external?.postMessage ||
    win.wails?.invoke,
  )
}

function previewAppSettings(): AppSettings {
  return {
    configDirectory: '',
    themeMode: 'system',
    showNavigationText: true,
    micaEnabled: true,
    topmost: false,
    notifications: true,
    autosaveLogCount: 5,
    runtimeDefaults: {},
  }
}

function previewShellState(): ShellState {
  return {
    appTitle: 'SurveyController',
    appVersion: 'preview',
    themeMode: 'system',
    currentPage: 'dashboard',
    topNav: [
      { id: 'dashboard', label: '概览', icon: 'home', section: 'top', selected: true },
      { id: 'runtime', label: '运行参数', icon: 'settings', section: 'top' },
      { id: 'strategy', label: '题目策略', icon: 'flow', section: 'top' },
      { id: 'reverse-fill', label: '反填', icon: 'refresh', section: 'top' },
      { id: 'logs', label: '日志', icon: 'document', section: 'top' },
    ],
    bottomNav: [
      { id: 'community', label: '社区', icon: 'chat', section: 'bottom' },
      { id: 'settings', label: '设置', icon: 'sliders', section: 'bottom' },
      { id: 'more', label: '更多', icon: 'grid', section: 'bottom' },
    ],
    dashboard: {
      surveyTitle: '未命名问卷',
      surveyUrl: '',
      targetCount: 1,
      threadCount: 1,
      randomIpEnabled: false,
      randomIpQuota: 0,
      randomIpQuotaLabel: '未同步',
      randomIpStatus: '未连接代理服务',
      randomIpStatusTone: '',
      proxySource: '默认',
      proxyAvailable: 0,
      proxyInUse: 0,
      questionCount: 0,
      progressCurrent: 0,
      progressTarget: 1,
      progressPercent: 0,
      statusText: '等待配置',
      platformLabel: '问卷星',
      metrics: [],
      quickActions: [],
      questionRows: [],
      sessionRows: [],
    },
    runtimeGroups: [],
    strategyRules: [],
    dimensionGroups: [],
    reverseFillPlan: [],
    logLines: [],
    communityItems: [],
    aboutItems: [],
    donateItems: [],
    ipUsageItems: [],
    settingsGroups: [],
  }
}
