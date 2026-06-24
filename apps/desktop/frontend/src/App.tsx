import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle } from 'lucide-react'
import { AppTheme, LoaderBusy } from 'react-windows-ui'
import { Dialogs } from '@wailsio/runtime'
import NavRail from './components/NavRail'
import WindowControls from './components/WindowControls'
import DashboardView from './pages/DashboardView'
import InfoView from './pages/InfoView'
import LogsView from './pages/LogsView'
import RuntimeView from './pages/RuntimeView'
import StrategyView from './pages/StrategyView'
import {
  buildDefaultConfig,
  cancelRuntimeConfig,
  loadAppModel,
  loadProxyStatus,
  loadRunTaskState,
  loadRuntimeConfig,
  previewReverseFill,
  saveRuntimeConfig,
  saveSettings,
  startRuntimeConfig,
} from './services/shell'
import {
  applyConfigToShell,
  updateAppSettingsField,
  updateRuntimeConfigField,
  type AppModel,
} from './services/stateMapper'
import type { ProxyStatus, RunTaskState, RuntimeConfig, ShellState } from './types'

function App() {
  const [platform, setPlatform] = useState<'windows' | 'macos' | 'linux' | 'unknown'>('unknown')

  useEffect(() => {
    const ua = navigator.userAgent.toLowerCase()
    let currentPlatform: 'windows' | 'macos' | 'linux' | 'unknown' = 'unknown'
    let platformClass = 'platform-unknown'

    if (ua.includes('windows')) {
      currentPlatform = 'windows'
      platformClass = 'platform-windows'
    } else if (ua.includes('macintosh') || ua.includes('mac os x')) {
      currentPlatform = 'macos'
      platformClass = 'platform-macos'
    } else if (ua.includes('linux')) {
      currentPlatform = 'linux'
      platformClass = 'platform-linux'
    }

    setPlatform(currentPlatform)
    document.documentElement.classList.add(platformClass)
    return () => {
      document.documentElement.classList.remove(platformClass)
    }
  }, [])

  const [model, setModel] = useState<AppModel | null>(null)
  const [currentPage, setCurrentPage] = useState('dashboard')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [runState, setRunState] = useState<RunTaskState | null>(null)
  const [proxyStatus, setProxyStatus] = useState<ProxyStatus | null>(null)
  const [runtimeLogLines, setRuntimeLogLines] = useState<string[]>([])
  const previousPage = useRef(currentPage)
  const runPollTimer = useRef<number | null>(null)

  const config = model?.config ?? null
  const runBusy = busy || Boolean(runState?.running || runState?.canceling)

  const shell = useMemo<ShellState | null>(() => {
    if (!model) {
      return null
    }
    const mapped = applyConfigToShell(
      model.shell,
      model.settings,
      model.config,
      model.reverseFillPreview,
      runState,
      proxyStatus,
    )
    return {
      ...mapped,
      logLines: [...runtimeLogLines, ...mapped.logLines].slice(0, 200),
    }
  }, [model, proxyStatus, runState, runtimeLogLines])

  const stopRunPolling = useCallback(() => {
    if (!runPollTimer.current) {
      return
    }
    window.clearInterval(runPollTimer.current)
    runPollTimer.current = null
  }, [])

  const pollRunState = useCallback(async () => {
    try {
      const [nextRun, nextProxy] = await Promise.all([loadRunTaskState(), loadProxyStatus()])
      setRunState(nextRun)
      setProxyStatus(nextProxy)
      if (!nextRun.running && !nextRun.canceling) {
        stopRunPolling()
        if (nextRun.events?.length) {
          setRuntimeLogLines((lines) => [
            ...nextRun.events!.map((event) => `[${event.worker || 'core'}] ${event.message}`),
            ...lines,
          ].slice(0, 200))
        }
      }
    } catch (err) {
      stopRunPolling()
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [stopRunPolling])

  const startRunPolling = useCallback(() => {
    if (runPollTimer.current) {
      return
    }
    runPollTimer.current = window.setInterval(() => {
      void pollRunState()
    }, 500)
    void pollRunState()
  }, [pollRunState])

  useEffect(() => {
    let ignore = false
    async function load() {
      try {
        const loaded = await loadAppModel()
        if (ignore) {
          return
        }
        setModel(loaded)
        setCurrentPage(loaded.shell.currentPage || 'dashboard')
        const [proxy, run] = await Promise.allSettled([loadProxyStatus(), loadRunTaskState()])
        if (ignore) {
          return
        }
        if (proxy.status === 'fulfilled') {
          setProxyStatus(proxy.value)
        }
        if (run.status === 'fulfilled') {
          setRunState(run.value)
          if (run.value.running) {
            startRunPolling()
          }
        }
      } catch (err) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : String(err))
        }
      } finally {
        if (!ignore) {
          setLoading(false)
        }
      }
    }
    void load()
    return () => {
      ignore = true
      stopRunPolling()
    }
  }, [startRunPolling, stopRunPolling])

  async function withBusy(action: () => Promise<void>) {
    setBusy(true)
    setError('')
    try {
      await action()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function setConfig(next: RuntimeConfig) {
    setModel((current) => current ? { ...current, config: next } : current)
  }

  function updateConfigField(id: string, value: string | boolean) {
    if (!config) {
      return
    }
    setConfig(updateRuntimeConfigField(config, id, value))
  }

  function updateSettingsField(id: string, value: string | boolean) {
    setModel((current) => current
      ? { ...current, settings: updateAppSettingsField(current.settings, id, value) }
      : current)
  }

  function updateURL(value: string) {
    if (!config) {
      return
    }
    setConfig({ ...config, url: value })
  }

  async function autoConfig() {
    await withBusy(async () => {
      if (!config?.url) {
        throw new Error('问卷链接不能为空')
      }
      const next = await buildDefaultConfig(config.url)
      setConfig({
        ...config,
        ...next,
        target: config.target,
        threads: config.threads,
        random_ip_enabled: config.random_ip_enabled,
        proxy_source: config.proxy_source,
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
      setModel((current) => current
        ? { ...current, configPath: loaded.path, config: loaded.config }
        : current)
      setNotice('配置已载入')
    })
  }

  async function saveConfigToDialog() {
    await withBusy(async () => {
      if (!config) {
        return
      }
      const path = await Dialogs.SaveFile({
        Title: '保存配置',
        Filename: `${config.survey_title || 'wjx_config'}.json`,
        Filters: [{ DisplayName: 'JSON 配置', Pattern: '*.json' }],
      })
      if (!path) {
        return
      }
      const saved = await saveRuntimeConfig(config, path)
      setModel((current) => current
        ? { ...current, configPath: saved.path, config: saved.config }
        : current)
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
      if (!path || Array.isArray(path) || !config) {
        return
      }
      setConfig({ ...config, reverse_fill_enabled: true, reverse_fill_source_path: path })
    })
  }

  async function previewReverseFillFile() {
    await withBusy(async () => {
      if (!config) {
        return
      }
      const preview = await previewReverseFill(config)
      setModel((current) => current ? { ...current, reverseFillPreview: preview } : current)
      setNotice(`已预览 ${preview.total_data_rows} 行`)
    })
  }

  async function saveAppSettings() {
    await withBusy(async () => {
      if (!model) {
        return
      }
      const saved = await saveSettings(model.settings)
      setModel((current) => current ? { ...current, settings: saved } : current)
      setNotice('设置已保存')
    })
  }

  async function runSurvey() {
    await withBusy(async () => {
      if (!config) {
        return
      }
      setRuntimeLogLines([])
      const nextRun = await startRuntimeConfig(config)
      const nextProxy = await loadProxyStatus()
      setRunState(nextRun)
      setProxyStatus(nextProxy)
      startRunPolling()
      setNotice('任务已启动')
    })
  }

  async function cancelRun() {
    await withBusy(async () => {
      const nextRun = await cancelRuntimeConfig()
      const nextProxy = await loadProxyStatus()
      setRunState(nextRun)
      setProxyStatus(nextProxy)
      startRunPolling()
      setNotice('正在停止任务')
    })
  }

  const scheme = shell?.themeMode === 'dark' || shell?.themeMode === 'light' ? shell.themeMode : 'system'
  const pageMotion = previousPage.current === currentPage ? 'page-motion-initial' : 'page-motion-forward'

  useEffect(() => {
    previousPage.current = currentPage
  }, [currentPage])

  if (loading) {
    return (
      <div className="boot-screen">
        <LoaderBusy isLoading />
      </div>
    )
  }

  if (error && !shell) {
    return (
      <div className="boot-screen">
        <div className="error-panel">
          <AlertCircle size={18} />
          <div>
            <strong>服务连接失败</strong>
            <span>{error}</span>
          </div>
        </div>
      </div>
    )
  }

  if (!shell) {
    return null
  }

  return (
    <div className="app-root">
      <AppTheme scheme={scheme} color="#0067c0" colorDarkMode="#60cdff" />
      <header className="app-titlebar drag-region">
        <div className="brand-block">
          <img className="app-logo" src="/appicon.png" alt="" draggable={false} />
          <div className="brand-text">
            <span>{shell.appTitle}</span>
            <small>{shell.appVersion}</small>
          </div>
        </div>
        {platform !== 'macos' && <WindowControls />}
      </header>

      <div className="app-frame">
        <NavRail
          topNav={shell.topNav}
          bottomNav={shell.bottomNav}
          currentPage={currentPage}
          onChange={setCurrentPage}
        />

        <main className="workspace">
          <div className="message-stack">
            {error ? <div className="status-banner status-banner-danger">{error}</div> : null}
            {notice ? <div className="status-banner status-banner-info">{notice}</div> : null}
          </div>

          <div key={currentPage} className={`page-transition ${pageMotion}`}>
            {currentPage === 'dashboard' ? (
              <DashboardView
                dashboard={shell.dashboard}
                logs={shell.logLines}
                busy={runBusy}
                onUpdateUrl={updateURL}
                onAutoConfig={autoConfig}
                onLoadConfig={loadConfigFromDialog}
                onSaveConfig={saveConfigToDialog}
                onOpenRuntime={() => setCurrentPage('runtime')}
                onTargetChange={(value) => updateConfigField('target', String(value))}
                onThreadsChange={(value) => updateConfigField('threads', String(value))}
                onRandomIpChange={(value) => updateConfigField('random-ip', value)}
                onProxySourceChange={(value) => updateConfigField('proxy-source', value)}
                onRun={runSurvey}
                onCancelRun={cancelRun}
              />
            ) : null}
            {currentPage === 'runtime' ? (
              <RuntimeView groups={shell.runtimeGroups} onFieldChange={updateConfigField} />
            ) : null}
            {currentPage === 'strategy' ? (
              <StrategyView rules={shell.strategyRules} dimensions={shell.dimensionGroups} />
            ) : null}
            {currentPage === 'reverse-fill' ? (
              <InfoView
                title="反填"
                reverseFill={shell.reverseFillPlan}
                reverseFillPath={config?.reverse_fill_source_path}
                busy={busy}
                onChooseReverseFill={chooseReverseFillFile}
                onPreviewReverseFill={previewReverseFillFile}
              />
            ) : null}
            {currentPage === 'logs' ? <LogsView logs={shell.logLines} /> : null}
            {currentPage === 'community' ? <InfoView title="社区" items={shell.communityItems} /> : null}
            {currentPage === 'settings' ? (
              <InfoView
                title="设置"
                settings={shell.settingsGroups}
                busy={busy}
                onSettingChange={updateSettingsField}
                onSaveSettings={saveAppSettings}
              />
            ) : null}
            {currentPage === 'more' ? (
              <InfoView title="更多" metrics={[...shell.aboutItems, ...shell.donateItems, ...shell.ipUsageItems]} />
            ) : null}
          </div>
        </main>
      </div>
    </div>
  )
}

export default App
