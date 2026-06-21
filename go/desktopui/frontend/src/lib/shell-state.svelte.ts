import type { ShellState } from './types'

const emptyState = (): ShellState => ({
  appTitle: 'SurveyController',
  appVersion: '0.0.0',
  themeMode: 'system',
  currentPage: 'dashboard',
  topNav: [],
  bottomNav: [],
  dashboard: {
    surveyTitle: '',
    surveyUrl: '',
    targetCount: 0,
    threadCount: 0,
    randomIpEnabled: false,
    randomIpQuota: 0,
    randomIpQuotaLabel: '',
    randomIpStatus: '',
    randomIpStatusTone: '',
    proxySource: '',
    questionCount: 0,
    progressCurrent: 0,
    progressTarget: 0,
    progressPercent: 0,
    statusText: '',
    platformLabel: '',
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
})

export const shellState = $state<{
  ready: boolean
  payload: ShellState
}>({
  ready: false,
  payload: emptyState(),
})

export function loadShellState(payload: unknown) {
  shellState.payload = payload as ShellState
  shellState.ready = true
}

export function setCurrentPage(page: string) {
  shellState.payload.currentPage = page
  shellState.payload.topNav = shellState.payload.topNav.map((item) => ({
    ...item,
    selected: item.id === page,
  }))
}

export function cycleThemeMode() {
  const current = shellState.payload.themeMode
  shellState.payload.themeMode =
    current === 'system' ? 'light' : current === 'light' ? 'dark' : 'system'
}
