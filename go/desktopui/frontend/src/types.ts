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
  kind: 'number' | 'slider' | 'range' | 'toggle' | 'select' | 'text' | string
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

export interface RuntimeConfig {
  url: string
  survey_title?: string
  survey_provider?: string
  target?: number
  threads?: number
  submit_interval?: number[]
  answer_duration?: number[]
  answer_datetime_window?: string[]
  random_ip_enabled?: boolean
  proxy_source?: string
  custom_proxy_api?: string
  proxy_area_code?: string | null
  random_ua_enabled?: boolean
  random_ua_ratios?: Record<string, number>
  fail_stop_enabled?: boolean
  pause_on_aliyun_captcha?: boolean
  reliability_mode_enabled?: boolean
  psycho_target_alpha?: number
  ai_mode?: string
  ai_provider?: string
  ai_api_key?: string
  ai_base_url?: string
  ai_api_protocol?: string
  ai_model?: string
  ai_system_prompt?: string
  reverse_fill_enabled?: boolean
  reverse_fill_source_path?: string
  reverse_fill_format?: string
  reverse_fill_start_row?: number
  reverse_fill_threads?: number
  answer_rules?: Record<string, unknown>[]
  dimension_groups?: string[]
  question_entries?: QuestionEntry[]
  questions_info?: QuestionMeta[]
}

export interface QuestionEntry {
  question_type: string
  probabilities: unknown
  question_num?: number | null
  question_title?: string | null
  survey_provider?: string
  distribution_mode?: string
  psycho_bias?: string
}

export interface QuestionMeta {
  num: number
  title: string
  description: string
  type_code: string
  options: number
  rows: number
  row_texts: string[]
  option_texts: string[]
  provider: string
  provider_type: string
  is_description: boolean
  is_text_like: boolean
  text_inputs: number
}

export interface AppSettings {
  configDirectory: string
  themeMode: string
  showNavigationText: boolean
  micaEnabled: boolean
  topmost: boolean
  notifications: boolean
  autosaveLogCount: number
  runtimeDefaults?: Record<string, string>
}

export interface ProxyStatus {
  available: number
  inUse: number
  remainingQuota: string
  totalQuota: string
  quotaKnown: boolean
  randomIpEnabled: boolean
  source: string
}

export interface RunEvent {
  worker: string
  message: string
  success: boolean
  fail: boolean
  current: number
  total: number
}

export interface RunResult {
  success: number
  fail: number
  stopped: boolean
}

export interface SurveyCoreState {
  config?: RuntimeConfig | null
  result?: RunResult | null
  events?: RunEvent[]
}

export interface ReverseFillPreview {
  source_path: string
  selected_format: string
  detected_format: string
  total_data_rows: number
  question_columns: Record<string, Array<{ column_index: number; header: string; question_num: number }>>
  sample_rows: Array<{ data_row_number: number; worksheet_row_number: number; answers: Record<string, unknown> }>
  unsupported_fields?: string[]
}
