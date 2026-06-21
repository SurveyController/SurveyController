import type {
  AppSettings,
  DashboardState,
  QuestionMeta,
  QuestionRow,
  ReverseFillPreview,
  ReverseFillRow,
  RuntimeConfig,
  SettingsGroup,
  ShellState,
} from '../types'

export interface AppModel {
  shell: ShellState
  settings: AppSettings
  config: RuntimeConfig
  configPath: string
  reverseFillPreview: ReverseFillPreview | null
}

const providerLabels: Record<string, string> = {
  wjx: '问卷星',
  qq: '腾讯问卷',
  credamo: '见数',
}

const proxyLabels: Record<string, string> = {
  default: '默认',
  benefit: '限时福利',
  custom: '自定义',
}

const proxyValues: Record<string, string> = Object.fromEntries(
  Object.entries(proxyLabels).map(([value, label]) => [label, value]),
)

export function buildAppModel(shell: ShellState, settings: AppSettings, config?: RuntimeConfig | null): AppModel {
  const runtimeConfig = normalizeRuntimeConfig(config ?? {
    url: shell.dashboard.surveyUrl,
    survey_title: shell.dashboard.surveyTitle,
    target: shell.dashboard.targetCount,
    threads: shell.dashboard.threadCount,
    random_ip_enabled: shell.dashboard.randomIpEnabled,
    proxy_source: 'default',
  })
  return {
    shell: applyConfigToShell(shell, settings, runtimeConfig, null),
    settings,
    config: runtimeConfig,
    configPath: '',
    reverseFillPreview: null,
  }
}

export function applyConfigToShell(
  shell: ShellState,
  settings: AppSettings,
  config: RuntimeConfig,
  preview: ReverseFillPreview | null,
): ShellState {
  const normalized = normalizeRuntimeConfig(config)
  return {
    ...shell,
    themeMode: settings.themeMode || shell.themeMode,
    dashboard: mapDashboard(shell.dashboard, normalized),
    runtimeGroups: mapRuntimeGroups(normalized),
    settingsGroups: mapSettingsGroups(settings),
    strategyRules: mapStrategyRules(normalized),
    dimensionGroups: normalized.dimension_groups ?? [],
    reverseFillPlan: mapReverseFillRows(normalized, preview),
  }
}

export function normalizeRuntimeConfig(config: RuntimeConfig): RuntimeConfig {
  const threads = clampInt(config.threads, 1, 128, 1)
  return {
    ...config,
    url: config.url ?? '',
    survey_title: config.survey_title ?? '',
    survey_provider: config.survey_provider ?? inferProvider(config.url),
    target: clampInt(config.target, 1, 999999, 1),
    threads,
    submit_interval: normalizePair(config.submit_interval, [0, 0]),
    answer_duration: normalizePair(config.answer_duration, [60, 120]),
    random_ip_enabled: Boolean(config.random_ip_enabled),
    proxy_source: config.proxy_source || 'default',
    random_ua_enabled: Boolean(config.random_ua_enabled),
    random_ua_ratios: config.random_ua_ratios ?? { wechat: 33, mobile: 33, pc: 34 },
    fail_stop_enabled: config.fail_stop_enabled ?? true,
    pause_on_aliyun_captcha: config.pause_on_aliyun_captcha ?? true,
    reliability_mode_enabled: config.reliability_mode_enabled ?? true,
    psycho_target_alpha: config.psycho_target_alpha ?? 0.85,
    ai_mode: config.ai_mode || 'free',
    ai_provider: config.ai_provider || 'deepseek',
    ai_api_protocol: config.ai_api_protocol || 'auto',
    reverse_fill_enabled: Boolean(config.reverse_fill_enabled),
    reverse_fill_format: config.reverse_fill_format || 'auto',
    reverse_fill_start_row: clampInt(config.reverse_fill_start_row, 1, 999999, 1),
    reverse_fill_threads: clampInt(config.reverse_fill_threads, 1, 128, threads),
    dimension_groups: config.dimension_groups ?? [],
    answer_rules: config.answer_rules ?? [],
    question_entries: config.question_entries ?? [],
    questions_info: config.questions_info ?? [],
  }
}

export function updateRuntimeConfigField(config: RuntimeConfig, fieldId: string, rawValue: string | boolean): RuntimeConfig {
  const next = normalizeRuntimeConfig(config)
  const text = String(rawValue)
  switch (fieldId) {
    case 'target':
      next.target = clampInt(Number(text), 1, 999999, 1)
      break
    case 'threads':
      next.threads = clampInt(Number(text), 1, 128, 1)
      next.reverse_fill_threads = Math.max(1, next.reverse_fill_threads ?? next.threads)
      break
    case 'random-ip':
      next.random_ip_enabled = Boolean(rawValue)
      break
    case 'proxy-source':
      next.proxy_source = proxyValues[text] ?? text
      break
    case 'random-ua':
      next.random_ua_enabled = Boolean(rawValue)
      break
    case 'fail-stop':
      next.fail_stop_enabled = Boolean(rawValue)
      break
    case 'pause-captcha':
      next.pause_on_aliyun_captcha = Boolean(rawValue)
      break
    case 'reverse-fill-enabled':
      next.reverse_fill_enabled = Boolean(rawValue)
      break
    case 'reverse-fill-path':
      next.reverse_fill_source_path = text
      break
    case 'reverse-fill-format':
      next.reverse_fill_format = text
      break
    case 'reverse-fill-start-row':
      next.reverse_fill_start_row = clampInt(Number(text), 1, 999999, 1)
      break
    case 'reverse-fill-threads':
      next.reverse_fill_threads = clampInt(Number(text), 1, 128, next.threads ?? 1)
      break
    case 'ai-mode':
      next.ai_mode = text
      break
    case 'ai-provider':
      next.ai_provider = text
      break
    case 'ai-model':
      next.ai_model = text
      break
    case 'ai-base-url':
      next.ai_base_url = text
      break
  }
  return normalizeRuntimeConfig(next)
}

export function updateAppSettingsField(settings: AppSettings, fieldId: string, rawValue: string | boolean): AppSettings {
  const next = { ...settings }
  const text = String(rawValue)
  switch (fieldId) {
    case 'nav-text':
      next.showNavigationText = Boolean(rawValue)
      break
    case 'mica':
      next.micaEnabled = Boolean(rawValue)
      break
    case 'topmost':
      next.topmost = Boolean(rawValue)
      break
    case 'notifications':
      next.notifications = Boolean(rawValue)
      break
    case 'autosave':
      next.autosaveLogCount = clampInt(Number(text), 1, 100, 5)
      break
    case 'theme':
      next.themeMode = text
      break
    case 'config-directory':
      next.configDirectory = text
      break
  }
  return next
}

export function questionTypeLabel(question: QuestionMeta): string {
  switch (question.provider_type || question.type_code) {
    case 'single':
    case 'radio':
    case '3':
      return '单选题'
    case 'multiple':
    case '4':
      return '多选题'
    case 'scale':
    case '5':
      return '量表题'
    case 'matrix':
    case 'matrix_radio':
    case '6':
      return '矩阵题'
    case 'dropdown':
    case 'select':
    case '7':
      return '下拉题'
    default:
      return '填空题'
  }
}

function mapDashboard(base: DashboardState, config: RuntimeConfig): DashboardState {
  const questions = config.questions_info ?? []
  const target = config.target ?? 1
  return {
    ...base,
    surveyTitle: config.survey_title || '未命名问卷',
    surveyUrl: config.url,
    targetCount: target,
    threadCount: config.threads ?? 1,
    randomIpEnabled: Boolean(config.random_ip_enabled),
    proxySource: proxyLabels[config.proxy_source ?? 'default'] ?? config.proxy_source ?? '默认',
    questionCount: questions.length,
    progressTarget: target,
    progressPercent: clampInt(base.progressPercent, 0, 100, 0),
    statusText: config.url ? '等待启动' : '等待配置',
    platformLabel: providerLabels[config.survey_provider ?? 'wjx'] ?? '问卷星',
    metrics: [
      { label: '已解析题目', value: String(questions.length) },
      { label: '当前并发', value: String(config.threads ?? 1) },
      { label: '随机 IP', value: config.random_ip_enabled ? '已启用' : '未启用', tone: config.random_ip_enabled ? 'success' : '' },
      { label: '反填', value: config.reverse_fill_enabled ? '已启用' : '未启用', tone: config.reverse_fill_enabled ? 'success' : '' },
    ],
    questionRows: mapQuestionRows(config),
  }
}

function mapRuntimeGroups(config: RuntimeConfig): SettingsGroup[] {
  const answerDuration = normalizePair(config.answer_duration, [60, 120])
  const submitInterval = normalizePair(config.submit_interval, [0, 0])
  return [
    {
      title: '执行参数',
      fields: [
        field('target', '目标份数', '限制本次任务的目标提交量', 'number', String(config.target ?? 1)),
        field('threads', '并发数', '纯 HTTP 并发，不走浏览器兜底', 'number', String(config.threads ?? 1)),
        field('interval', '提交间隔', '每份提交之间的等待范围', 'range', `${submitInterval[0]}s - ${submitInterval[1]}s`),
        field('answer-duration', '作答时长', '控制整卷耗时分布', 'range', `${answerDuration[0]}s - ${answerDuration[1]}s`),
      ],
    },
    {
      title: '代理与身份',
      fields: [
        field('random-ip', '随机 IP', '启用后按会话申请代理', 'toggle', String(Boolean(config.random_ip_enabled))),
        field('proxy-source', '代理源', '默认 / 福利 / 自定义', 'select', proxyLabels[config.proxy_source ?? 'default'] ?? '默认', ['默认', '限时福利', '自定义']),
        field('random-ua', '随机 UA', '拆散重复指纹', 'toggle', String(Boolean(config.random_ua_enabled))),
        field('fail-stop', '失败停止', '失败过多时停止任务', 'toggle', String(config.fail_stop_enabled ?? true)),
      ],
    },
    {
      title: 'AI 与反填',
      fields: [
        field('ai-mode', 'AI 模式', '免费模式或自定义服务商', 'select', config.ai_mode ?? 'free', ['free', 'provider']),
        field('ai-provider', 'AI 服务商', 'DeepSeek / OpenAI 兼容服务', 'text', config.ai_provider ?? 'deepseek'),
        field('ai-model', 'AI 模型', '用于文本题生成和改写', 'text', config.ai_model ?? ''),
        field('reverse-fill-enabled', 'Excel 反填', '按导出的 Excel 回放答案', 'toggle', String(Boolean(config.reverse_fill_enabled))),
        field('reverse-fill-path', '反填文件', 'xlsx 文件路径', 'text', config.reverse_fill_source_path ?? ''),
        field('reverse-fill-format', '反填格式', '问卷星导出格式', 'select', config.reverse_fill_format ?? 'auto', ['auto', 'wjx_text', 'wjx_score', 'wjx_sequence']),
        field('reverse-fill-start-row', '起始行', 'Excel 数据起始行', 'number', String(config.reverse_fill_start_row ?? 1)),
        field('reverse-fill-threads', '反填并发', '反填任务并发数', 'number', String(config.reverse_fill_threads ?? config.threads ?? 1)),
      ],
    },
  ]
}

function mapSettingsGroups(settings: AppSettings): SettingsGroup[] {
  return [
    {
      title: '界面外观',
      fields: [
        field('theme', '主题', '跟随系统或固定明暗色', 'select', settings.themeMode || 'system', ['system', 'light', 'dark']),
        field('nav-text', '显示导航文本', '贴近 QFluentWidgets 侧栏表现', 'toggle', String(settings.showNavigationText)),
        field('mica', '启用 Mica 背景', 'WinUI 3 风格窗口材质', 'toggle', String(settings.micaEnabled)),
      ],
    },
    {
      title: '行为设置',
      fields: [
        field('topmost', '窗口置顶', '任务运行时便于观察', 'toggle', String(settings.topmost)),
        field('notifications', '系统通知', '任务结束后弹系统通知', 'toggle', String(settings.notifications)),
        field('autosave', '自动保存日志', '保留最近几份日志', 'select', String(settings.autosaveLogCount || 5), ['3', '5', '10']),
        field('config-directory', '配置目录', '载入和保存配置的默认目录', 'text', settings.configDirectory || ''),
      ],
    },
  ]
}

function mapQuestionRows(config: RuntimeConfig): QuestionRow[] {
  const entries = config.question_entries ?? []
  return (config.questions_info ?? []).filter((question) => !question.is_description).map((question) => {
    const entry = entries.find((item) => item.question_num === question.num)
    return {
      index: question.num,
      type: questionTypeLabel(question),
      dimension: (config.dimension_groups ?? [])[question.num - 1] ?? '',
      strategy: String(entry?.distribution_mode || entry?.psycho_bias || '随机'),
    }
  })
}

function mapStrategyRules(config: RuntimeConfig) {
  return (config.answer_rules ?? []).map((rule, index) => ({
    condition: String(rule.condition ?? `规则 ${index + 1}`),
    action: String(rule.action ?? '约束'),
    target: String(rule.target ?? ''),
  }))
}

function mapReverseFillRows(config: RuntimeConfig, preview: ReverseFillPreview | null): ReverseFillRow[] {
  const columns = preview?.question_columns ?? {}
  const questions = config.questions_info ?? []
  if (!questions.length) {
    return []
  }
  return questions.map((question) => {
    const matched = columns[String(question.num)] ?? []
    return {
      question: `第 ${question.num} 题`,
      column: matched.map((item) => item.header).join(', ') || '-',
      state: matched.length ? `已匹配 ${preview?.total_data_rows ?? 0} 行` : '未匹配',
    }
  })
}

function field(id: string, label: string, description: string, kind: string, value: string, options?: string[]) {
  return { id, label, description, kind, value, options }
}

function inferProvider(url: string): string {
  const normalized = (url || '').toLowerCase()
  if (normalized.includes('wj.qq.com')) {
    return 'qq'
  }
  if (normalized.includes('credamo')) {
    return 'credamo'
  }
  return 'wjx'
}

function normalizePair(value: number[] | undefined, fallback: [number, number]): [number, number] {
  if (!value || value.length < 2) {
    return fallback
  }
  const left = clampInt(value[0], 0, 999999, fallback[0])
  const right = clampInt(value[1], left, 999999, fallback[1])
  return [left, right]
}

function clampInt(value: unknown, min: number, max: number, fallback: number): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) {
    return fallback
  }
  return Math.max(min, Math.min(max, Math.trunc(parsed)))
}
