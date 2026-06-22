package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"sync"
	"time"

	"surveycontroller/proxycore"
	"surveycontroller/surveycore"
	"surveycontroller/surveycore/configio"
	"surveycontroller/surveycore/reversefill"
)

type NavItem struct {
	ID       string `json:"id"`
	Label    string `json:"label"`
	Icon     string `json:"icon"`
	Section  string `json:"section"`
	Badge    string `json:"badge,omitempty"`
	Selected bool   `json:"selected,omitempty"`
}

type PageMetric struct {
	Label string `json:"label"`
	Value string `json:"value"`
	Tone  string `json:"tone,omitempty"`
}

type QuickAction struct {
	ID       string `json:"id"`
	Label    string `json:"label"`
	Icon     string `json:"icon"`
	Emphasis string `json:"emphasis,omitempty"`
}

type QuestionRow struct {
	Index     int    `json:"index"`
	Type      string `json:"type"`
	Dimension string `json:"dimension"`
	Strategy  string `json:"strategy"`
}

type SessionRow struct {
	Thread   string `json:"thread"`
	Status   string `json:"status"`
	Progress int    `json:"progress"`
}

type ParseSurveyRequest struct {
	URL string `json:"url"`
}

type RunSurveyRequest struct {
	Config surveycore.RuntimeConfig `json:"config"`
}

type RunTaskState struct {
	Running   bool                      `json:"running"`
	Canceling bool                      `json:"canceling"`
	Result    *surveycore.RunResult     `json:"result,omitempty"`
	Events    []surveycore.Event        `json:"events,omitempty"`
	Error     string                    `json:"error,omitempty"`
	StartedAt time.Time                 `json:"startedAt,omitempty"`
	EndedAt   time.Time                 `json:"endedAt,omitempty"`
	Config    *surveycore.RuntimeConfig `json:"config,omitempty"`
}

type ReverseFillPreviewRequest struct {
	Path      string                    `json:"path"`
	Format    string                    `json:"format"`
	StartRow  int                       `json:"startRow"`
	Questions []surveycore.QuestionMeta `json:"questions"`
}

type SurveyCoreState struct {
	Definition *surveycore.SurveyDefinition `json:"definition,omitempty"`
	Config     *surveycore.RuntimeConfig    `json:"config,omitempty"`
	Result     *surveycore.RunResult        `json:"result,omitempty"`
	Events     []surveycore.Event           `json:"events,omitempty"`
}

type ProxyStatus struct {
	Available       int                     `json:"available"`
	InUse           int                     `json:"inUse"`
	RemainingQuota  string                  `json:"remainingQuota"`
	TotalQuota      string                  `json:"totalQuota"`
	QuotaKnown      bool                    `json:"quotaKnown"`
	RandomIPEnabled bool                    `json:"randomIpEnabled"`
	Source          string                  `json:"source"`
	Message         string                  `json:"message"`
	Quota           proxycore.QuotaSnapshot `json:"quota"`
}

type DashboardState struct {
	SurveyTitle        string        `json:"surveyTitle"`
	SurveyURL          string        `json:"surveyUrl"`
	TargetCount        int           `json:"targetCount"`
	ThreadCount        int           `json:"threadCount"`
	RandomIPEnabled    bool          `json:"randomIpEnabled"`
	RandomIPQuota      int           `json:"randomIpQuota"`
	RandomIPQuotaLabel string        `json:"randomIpQuotaLabel"`
	RandomIPStatus     string        `json:"randomIpStatus"`
	RandomIPStatusTone string        `json:"randomIpStatusTone"`
	ProxySource        string        `json:"proxySource"`
	QuestionCount      int           `json:"questionCount"`
	ProgressCurrent    int           `json:"progressCurrent"`
	ProgressTarget     int           `json:"progressTarget"`
	ProgressPercent    int           `json:"progressPercent"`
	StatusText         string        `json:"statusText"`
	PlatformLabel      string        `json:"platformLabel"`
	Metrics            []PageMetric  `json:"metrics"`
	QuickActions       []QuickAction `json:"quickActions"`
	QuestionRows       []QuestionRow `json:"questionRows"`
	SessionRows        []SessionRow  `json:"sessionRows"`
}

type SettingField struct {
	ID          string   `json:"id"`
	Label       string   `json:"label"`
	Description string   `json:"description"`
	Kind        string   `json:"kind"`
	Value       string   `json:"value"`
	Options     []string `json:"options,omitempty"`
}

type SettingsGroup struct {
	Title  string         `json:"title"`
	Fields []SettingField `json:"fields"`
}

type StrategyRule struct {
	Condition string `json:"condition"`
	Action    string `json:"action"`
	Target    string `json:"target"`
}

type ReverseFillRow struct {
	Question string `json:"question"`
	Column   string `json:"column"`
	State    string `json:"state"`
}

type ShellState struct {
	AppTitle        string           `json:"appTitle"`
	AppVersion      string           `json:"appVersion"`
	ThemeMode       string           `json:"themeMode"`
	CurrentPage     string           `json:"currentPage"`
	TopNav          []NavItem        `json:"topNav"`
	BottomNav       []NavItem        `json:"bottomNav"`
	Dashboard       DashboardState   `json:"dashboard"`
	RuntimeGroups   []SettingsGroup  `json:"runtimeGroups"`
	StrategyRules   []StrategyRule   `json:"strategyRules"`
	DimensionGroups []string         `json:"dimensionGroups"`
	ReverseFillPlan []ReverseFillRow `json:"reverseFillPlan"`
	LogLines        []string         `json:"logLines"`
	CommunityItems  []string         `json:"communityItems"`
	AboutItems      []PageMetric     `json:"aboutItems"`
	DonateItems     []PageMetric     `json:"donateItems"`
	IPUsageItems    []PageMetric     `json:"ipUsageItems"`
	SettingsGroups  []SettingsGroup  `json:"settingsGroups"`
}

type AppService struct {
	survey  *surveycore.Client
	runMu   sync.Mutex
	proxyMu sync.Mutex
	run     RunTaskState
	cancel  context.CancelFunc
	proxy   *proxyRuntime
}

func NewAppService() *AppService {
	return &AppService{survey: surveycore.New(), proxy: newProxyRuntime()}
}

func (s *AppService) surveyClient() *surveycore.Client {
	if s.survey != nil {
		return s.survey
	}
	return surveycore.New()
}

func (s *AppService) proxyRuntime() *proxyRuntime {
	s.proxyMu.Lock()
	defer s.proxyMu.Unlock()
	if s.proxy == nil {
		s.proxy = newProxyRuntime()
	}
	return s.proxy
}

func (s *AppService) GetShellState() ShellState {
	return ShellState{
		AppTitle:    "SurveyController",
		AppVersion:  displayAppVersion(),
		ThemeMode:   "system",
		CurrentPage: "dashboard",
		TopNav: []NavItem{
			{ID: "dashboard", Label: "概览", Icon: "home", Section: "top", Selected: true},
			{ID: "runtime", Label: "运行参数", Icon: "settings", Section: "top"},
			{ID: "strategy", Label: "题目策略", Icon: "flow", Section: "top"},
			{ID: "reverse-fill", Label: "反填", Icon: "refresh", Section: "top", Badge: "预览"},
			{ID: "logs", Label: "日志", Icon: "document", Section: "top"},
		},
		BottomNav: []NavItem{
			{ID: "community", Label: "社区", Icon: "chat", Section: "bottom"},
			{ID: "settings", Label: "设置", Icon: "sliders", Section: "bottom"},
			{ID: "more", Label: "更多", Icon: "grid", Section: "bottom"},
		},
		Dashboard: DashboardState{
			SurveyTitle:        "大学生消费观问卷",
			SurveyURL:          "https://www.wjx.cn/vm/example.aspx#",
			TargetCount:        240,
			ThreadCount:        8,
			RandomIPEnabled:    true,
			RandomIPQuota:      68,
			RandomIPQuotaLabel: "6,820 / 10,000",
			RandomIPStatus:     "代理额度稳定",
			RandomIPStatusTone: "success",
			ProxySource:        "默认",
			QuestionCount:      18,
			ProgressCurrent:    96,
			ProgressTarget:     240,
			ProgressPercent:    0,
			StatusText:         "等待启动",
			PlatformLabel:      "问卷星",
			Metrics: []PageMetric{
				{Label: "已解析题目", Value: "18"},
				{Label: "当前并发", Value: "8"},
				{Label: "随机 IP", Value: "已启用", Tone: "success"},
				{Label: "设备风控", Value: "低", Tone: "success"},
			},
			QuickActions: []QuickAction{
				{ID: "parse", Label: "解析问卷", Icon: "scan", Emphasis: "primary"},
				{ID: "load-config", Label: "载入配置", Icon: "folder"},
				{ID: "save-config", Label: "保存配置", Icon: "save"},
				{ID: "open-runtime", Label: "高级参数", Icon: "tune"},
			},
			QuestionRows: []QuestionRow{
				{Index: 1, Type: "单选题", Dimension: "消费频率", Strategy: "正态分布偏高"},
				{Index: 2, Type: "多选题", Dimension: "消费场景", Strategy: "按维度约束"},
				{Index: 3, Type: "量表题", Dimension: "品牌偏好", Strategy: "轻度正向偏置"},
				{Index: 4, Type: "填空题", Dimension: "意见反馈", Strategy: "AI 改写"},
			},
			SessionRows: []SessionRow{},
		},
		RuntimeGroups: []SettingsGroup{
			{
				Title: "执行参数",
				Fields: []SettingField{
					{ID: "target", Label: "目标份数", Description: "限制本次任务的目标提交量", Kind: "number", Value: "240"},
					{ID: "threads", Label: "并发数", Description: "纯 HTTP 并发，不走浏览器兜底", Kind: "slider", Value: "8"},
					{ID: "interval", Label: "提交间隔", Description: "模拟真实提交节奏", Kind: "range", Value: "8s - 26s"},
				},
			},
			{
				Title: "代理与身份",
				Fields: []SettingField{
					{ID: "random-ip", Label: "随机 IP", Description: "启用后按会话申请代理", Kind: "toggle", Value: "true"},
					{ID: "proxy-source", Label: "代理源", Description: "默认 / 福利 / 自定义", Kind: "select", Value: "默认", Options: []string{"默认", "限时福利", "自定义"}},
					{ID: "random-ua", Label: "随机 UA", Description: "拆散重复指纹", Kind: "toggle", Value: "true"},
				},
			},
			{
				Title: "作答行为",
				Fields: []SettingField{
					{ID: "answer-duration", Label: "作答时长", Description: "控制整卷耗时分布", Kind: "range", Value: "160s - 420s"},
					{ID: "answer-window", Label: "提交时段", Description: "限制一天中的提交窗口", Kind: "select", Value: "全天", Options: []string{"全天", "工作时段", "晚间"}},
					{ID: "reliability", Label: "稳定性", Description: "提交失败时重试与保守模式", Kind: "select", Value: "平衡", Options: []string{"保守", "平衡", "激进"}},
				},
			},
		},
		StrategyRules: []StrategyRule{
			{Condition: "选择 1. 奶茶", Action: "下一题必须选", Target: "2. 饮品类消费"},
			{Condition: "选择 3. 电子产品", Action: "下一题禁止选", Target: "4. 冲动消费"},
			{Condition: "量表均值 > 4", Action: "维持同向偏置", Target: "5. 品牌满意度"},
		},
		DimensionGroups: []string{
			"消费能力",
			"消费场景",
			"品牌偏好",
			"情绪驱动",
		},
		ReverseFillPlan: []ReverseFillRow{
			{Question: "第 1 题", Column: "A 列", State: "已匹配"},
			{Question: "第 2 题", Column: "C 列", State: "已匹配"},
			{Question: "第 4 题", Column: "F 列", State: "待校验"},
			{Question: "第 6 题", Column: "I 列", State: "缺少配置"},
		},
		LogLines: []string{
			"[10:14:09] UI 载入 Fluent 壳层",
			"[10:14:11] Core 服务未接入，当前使用假数据",
			"[10:14:13] 随机 IP 卡片状态同步完成",
			"[10:14:16] 概览页题目表格已渲染",
		},
		CommunityItems: []string{
			"反馈 WinUI 3 细节偏差",
			"补齐问卷平台解析预览",
			"整理 Fluent 组件替换清单",
		},
		AboutItems: []PageMetric{
			{Label: "版本", Value: displayAppVersion()},
			{Label: "前端栈", Value: "Vue 3 + TailwindCSS + Wails v3"},
			{Label: "桌面壳", Value: "Wails v3"},
		},
		DonateItems: []PageMetric{
			{Label: "支持方向", Value: "代理额度与平台适配"},
			{Label: "当前阶段", Value: "UI alpha"},
		},
		IPUsageItems: []PageMetric{
			{Label: "今日已扣", Value: "1,280"},
			{Label: "福利倍率", Value: "0.5x", Tone: "success"},
			{Label: "最近同步", Value: "2 分钟前"},
		},
		SettingsGroups: []SettingsGroup{
			{
				Title: "界面外观",
				Fields: []SettingField{
					{ID: "nav-text", Label: "显示导航文本", Description: "贴近 QFluentWidgets 侧栏表现", Kind: "toggle", Value: "true"},
					{ID: "mica", Label: "启用 Mica 背景", Description: "WinUI 3 风格窗口材质", Kind: "toggle", Value: "true"},
				},
			},
			{
				Title: "行为设置",
				Fields: []SettingField{
					{ID: "topmost", Label: "窗口置顶", Description: "任务运行时便于观察", Kind: "toggle", Value: "false"},
					{ID: "notifications", Label: "系统通知", Description: "任务结束后弹系统通知", Kind: "toggle", Value: "true"},
					{ID: "autosave", Label: "自动保存日志", Description: "保留最近 5 份日志", Kind: "select", Value: "5", Options: []string{"3", "5", "10"}},
				},
			},
		},
	}
}

func (s *AppService) GetProxyStatus() ProxyStatus {
	return s.proxyRuntime().statusSnapshot()
}

func (s *AppService) GetAppSettings() (AppSettings, error) {
	return loadAppSettings()
}

func (s *AppService) SaveAppSettings(_ context.Context, request SaveSettingsRequest) (AppSettings, error) {
	return saveAppSettings(request.Settings)
}

func (s *AppService) LoadConfig(_ context.Context, request LoadConfigRequest) (ConfigFileState, error) {
	settings, err := loadAppSettings()
	if err != nil {
		return ConfigFileState{}, err
	}
	path := configPathFromRequest(request.Path, settings)
	cfg, err := configio.Load(path, true)
	if err != nil {
		if strings.TrimSpace(request.Path) == "" && errors.Is(err, os.ErrNotExist) {
			empty := surveycore.RuntimeConfig{}
			return ConfigFileState{Path: path, Config: &empty}, nil
		}
		return ConfigFileState{}, err
	}
	return ConfigFileState{Path: path, Config: &cfg}, nil
}

func (s *AppService) SaveConfig(_ context.Context, request SaveConfigRequest) (ConfigFileState, error) {
	settings, err := loadAppSettings()
	if err != nil {
		return ConfigFileState{}, err
	}
	path := strings.TrimSpace(request.Path)
	if path == "" {
		path = defaultSavePath(request.Config, settings)
	}
	savedPath, err := configio.Save(request.Config, path)
	if err != nil {
		return ConfigFileState{}, err
	}
	cfg := request.Config
	return ConfigFileState{Path: savedPath, Config: &cfg}, nil
}

func (s *AppService) PreviewReverseFill(_ context.Context, request ReverseFillPreviewRequest) (reversefill.Preview, error) {
	return reversefill.PreviewExcel(reversefill.PreviewOptions{
		Path:          request.Path,
		Format:        request.Format,
		StartRow:      request.StartRow,
		Questions:     request.Questions,
		MaxSampleRows: 20,
	})
}

func (s *AppService) ParseSurvey(ctx context.Context, request ParseSurveyRequest) (SurveyCoreState, error) {
	url := strings.TrimSpace(request.URL)
	if url == "" {
		return SurveyCoreState{}, fmt.Errorf("问卷链接不能为空")
	}
	definition, err := s.surveyClient().Parse(ctx, url)
	if err != nil {
		return SurveyCoreState{}, err
	}
	return SurveyCoreState{Definition: definition}, nil
}

func (s *AppService) BuildDefaultConfig(ctx context.Context, request ParseSurveyRequest) (SurveyCoreState, error) {
	url := strings.TrimSpace(request.URL)
	if url == "" {
		return SurveyCoreState{}, fmt.Errorf("问卷链接不能为空")
	}
	config, err := s.surveyClient().DefaultConfig(ctx, url)
	if err != nil {
		return SurveyCoreState{}, err
	}
	return SurveyCoreState{Config: config}, nil
}

func (s *AppService) RunSurvey(ctx context.Context, request RunSurveyRequest) (SurveyCoreState, error) {
	var (
		events   []surveycore.Event
		eventsMu sync.Mutex
	)
	options, err := s.proxyRuntime().executionOptions(ctx, request.Config)
	if err != nil {
		return SurveyCoreState{}, err
	}
	result, err := s.surveyClient().RunWithExecutionOptions(ctx, &request.Config, func(event surveycore.Event) {
		eventsMu.Lock()
		events = append(events, event)
		eventsMu.Unlock()
	}, options)
	if err != nil {
		return SurveyCoreState{Result: result, Events: events}, err
	}
	return SurveyCoreState{Result: result, Events: events}, nil
}

func (s *AppService) StartRun(ctx context.Context, request RunSurveyRequest) (RunTaskState, error) {
	s.runMu.Lock()
	if s.run.Running {
		state := s.cloneRunStateLocked()
		s.runMu.Unlock()
		return state, fmt.Errorf("任务正在运行")
	}
	cfg := request.Config
	options, err := s.proxyRuntime().executionOptions(ctx, cfg)
	if err != nil {
		state := s.cloneRunStateLocked()
		s.runMu.Unlock()
		return state, err
	}
	runCtx, cancel := context.WithCancel(context.Background())
	s.cancel = cancel
	s.run = RunTaskState{
		Running:   true,
		StartedAt: time.Now(),
		Config:    &cfg,
		Events:    []surveycore.Event{},
	}
	state := s.cloneRunStateLocked()
	s.runMu.Unlock()

	go s.runSurveyTask(runCtx, cfg, options)
	return state, nil
}

func (s *AppService) GetRunTaskState() RunTaskState {
	s.runMu.Lock()
	defer s.runMu.Unlock()
	return s.cloneRunStateLocked()
}

func (s *AppService) CancelRun(_ context.Context) (RunTaskState, error) {
	s.runMu.Lock()
	if s.cancel != nil && s.run.Running {
		s.run.Canceling = true
		s.cancel()
	}
	state := s.cloneRunStateLocked()
	s.runMu.Unlock()
	return state, nil
}

func (s *AppService) runSurveyTask(ctx context.Context, cfg surveycore.RuntimeConfig, options surveycore.ExecutionOptions) {
	result, err := s.surveyClient().RunWithExecutionOptions(ctx, &cfg, func(event surveycore.Event) {
		s.runMu.Lock()
		s.run.Events = append(s.run.Events, event)
		s.runMu.Unlock()
	}, options)
	s.runMu.Lock()
	defer s.runMu.Unlock()
	s.run.Running = false
	s.run.Canceling = false
	s.run.Result = result
	s.run.EndedAt = time.Now()
	if err != nil {
		s.run.Error = err.Error()
	} else {
		s.run.Error = ""
	}
	s.cancel = nil
}

func (s *AppService) cloneRunStateLocked() RunTaskState {
	state := s.run
	state.Events = append([]surveycore.Event(nil), s.run.Events...)
	if s.run.Config != nil {
		cfg := *s.run.Config
		state.Config = &cfg
	}
	return state
}
