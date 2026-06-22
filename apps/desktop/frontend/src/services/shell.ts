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
import { mockShellState } from './mockShellState'
import { buildAppModel, type AppModel } from './stateMapper'

export async function loadShellState(): Promise<ShellState> {
  try {
    return (await GetShellState()) as ShellState
  } catch (err) {
    if (import.meta.env.DEV) {
      return mockShellState
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
    if (import.meta.env.DEV) {
      return buildAppModel(mockShellState, mockAppSettings(), null)
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

function mockAppSettings(): AppSettings {
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
