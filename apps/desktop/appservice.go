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
	return initialShellState(displayAppVersion())
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
