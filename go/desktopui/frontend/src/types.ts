export type Tone = string

export interface NavItem {
  id: string
  label: string
  icon: string
  section: string
  badge?: string
  selected?: boolean
}

export interface PageMetric {
  label: string
  value: string
  tone?: Tone
}

export interface QuickAction {
  id: string
  label: string
  icon: string
  emphasis?: 'primary' | string
}

export interface QuestionRow {
  index: number
  type: string
  dimension: string
  strategy: string
}

export interface SessionRow {
  thread: string
  status: string
  progress: number
}

export interface DashboardState {
  surveyTitle: string
  surveyUrl: string
  targetCount: number
  threadCount: number
  randomIpEnabled: boolean
  randomIpQuota: number
  randomIpQuotaLabel: string
  randomIpStatus: string
  randomIpStatusTone: Tone
  proxySource: string
  questionCount: number
  progressCurrent: number
  progressTarget: number
  progressPercent: number
  statusText: string
  platformLabel: string
  metrics: PageMetric[]
  quickActions: QuickAction[]
  questionRows: QuestionRow[]
  sessionRows: SessionRow[]
}

export interface SettingField {
  id: string
  label: string
  description: string
  kind: 'number' | 'slider' | 'range' | 'toggle' | 'select' | string
  value: string
  options?: string[]
}

export interface SettingsGroup {
  title: string
  fields: SettingField[]
}

export interface StrategyRule {
  condition: string
  action: string
  target: string
}

export interface ReverseFillRow {
  question: string
  column: string
  state: string
}

export interface ShellState {
  appTitle: string
  appVersion: string
  themeMode: string
  currentPage: string
  topNav: NavItem[]
  bottomNav: NavItem[]
  dashboard: DashboardState
  runtimeGroups: SettingsGroup[]
  strategyRules: StrategyRule[]
  dimensionGroups: string[]
  reverseFillPlan: ReverseFillRow[]
  logLines: string[]
  communityItems: string[]
  aboutItems: PageMetric[]
  donateItems: PageMetric[]
  ipUsageItems: PageMetric[]
  settingsGroups: SettingsGroup[]
}
