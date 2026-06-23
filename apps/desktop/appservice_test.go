package main

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/xuri/excelize/v2"
	"surveycontroller/surveycore"
)

func TestAppServiceRejectsEmptySurveyURL(t *testing.T) {
	service := NewAppService()
	_, err := service.ParseSurvey(context.Background(), ParseSurveyRequest{})
	if err == nil || !strings.Contains(err.Error(), "问卷链接不能为空") {
		t.Fatalf("err = %v", err)
	}

	_, err = service.BuildDefaultConfig(context.Background(), ParseSurveyRequest{})
	if err == nil || !strings.Contains(err.Error(), "问卷链接不能为空") {
		t.Fatalf("err = %v", err)
	}
}

func TestAppServiceProxyStatusUsesCoreTypes(t *testing.T) {
	service := NewAppService()
	status := service.GetProxyStatus()
	if status.Available != 0 || status.InUse != 0 || status.RemainingQuota != "0" {
		t.Fatalf("status = %#v", status)
	}
}

func TestAppServiceShellStateStartsFromRealEmptyState(t *testing.T) {
	service := NewAppService()
	state := service.GetShellState()
	if state.Dashboard.SurveyURL != "" || state.Dashboard.QuestionCount != 0 || state.Dashboard.ProgressCurrent != 0 {
		t.Fatalf("dashboard = %#v", state.Dashboard)
	}
	if state.Dashboard.SurveyTitle == "大学生消费观问卷" {
		t.Fatalf("shell state still contains demo survey: %#v", state.Dashboard)
	}
	for _, line := range state.LogLines {
		if strings.Contains(line, "假数据") || strings.Contains(line, "未接入") {
			t.Fatalf("shell state contains mock log line: %q", line)
		}
	}
}

func TestConfigVersionFromTextReadsInfoVersion(t *testing.T) {
	version := configVersionFromText(`
version: '3'

info:
  productName: "SurveyController"
  version: "9.8.7" # 应用版本号
`)
	if version != "9.8.7" {
		t.Fatalf("version = %q", version)
	}
}

func TestAppServiceProxyRuntimeUsesCustomAPI(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		writeAppJSON(t, w, map[string]any{"data": []string{"1.2.3.4:9000"}})
	}))
	defer server.Close()

	service := NewAppService()
	options, err := service.proxyRuntime().executionOptions(context.Background(), surveycore.RuntimeConfig{
		RandomIPEnabled: true,
		ProxySource:     "custom",
		CustomProxyAPI:  server.URL,
		Threads:         2,
	})
	if err != nil {
		t.Fatal(err)
	}
	if options.LeaseManager == nil {
		t.Fatal("lease manager is nil")
	}
	lease, err := options.LeaseManager.Acquire(context.Background(), "worker-1")
	if err != nil {
		t.Fatal(err)
	}
	if lease.Address != "http://1.2.3.4:9000" || lease.Source != "custom" {
		t.Fatalf("lease = %#v", lease)
	}
	status := service.GetProxyStatus()
	if status.Source != "custom" || status.InUse != 1 || status.Message != "自定义代理已连接" {
		t.Fatalf("status = %#v", status)
	}
	if _, ok := options.LeaseManager.Release("worker-1"); !ok {
		t.Fatal("lease was not released")
	}
	if status = service.GetProxyStatus(); status.InUse != 0 {
		t.Fatalf("status after release = %#v", status)
	}
}

func TestAppServiceProxyRuntimeRejectsUnsupportedOfficialSource(t *testing.T) {
	service := NewAppService()
	_, err := service.proxyRuntime().executionOptions(context.Background(), surveycore.RuntimeConfig{
		RandomIPEnabled: true,
		ProxySource:     "default",
	})
	if !errors.Is(err, surveycore.ErrUnsupportedOperation) {
		t.Fatalf("err = %v", err)
	}
	status := service.GetProxyStatus()
	if status.Message != "官方代理源未接入" {
		t.Fatalf("status = %#v", status)
	}
}

func TestAppServiceParsesTencentViaCoreClient(t *testing.T) {
	server := newAppTencentServer(t)
	defer server.Close()
	service := &AppService{survey: surveycore.New(surveycore.WithHTTPClient(rewriteTencentClient(server.URL)))}

	state, err := service.ParseSurvey(context.Background(), ParseSurveyRequest{URL: "https://wj.qq.com/s2/123/hashvalue/"})
	if err != nil {
		t.Fatal(err)
	}
	if state.Definition == nil || state.Definition.Provider != surveycore.ProviderQQ || len(state.Definition.Questions) != 2 {
		t.Fatalf("state = %#v", state)
	}

	configState, err := service.BuildDefaultConfig(context.Background(), ParseSurveyRequest{URL: "https://wj.qq.com/s2/123/hashvalue/"})
	if err != nil {
		t.Fatal(err)
	}
	if configState.Config == nil || configState.Config.SurveyProvider != surveycore.ProviderQQ || len(configState.Config.QuestionsInfo) != 2 {
		t.Fatalf("configState = %#v", configState)
	}
}

func TestAppServiceParsesCredamoViaCoreClient(t *testing.T) {
	server := newAppCredamoServer(t)
	defer server.Close()
	service := NewAppService()

	state, err := service.ParseSurvey(context.Background(), ParseSurveyRequest{URL: server.URL + "/s/demo_"})
	if err != nil {
		t.Fatal(err)
	}
	if state.Definition == nil || state.Definition.Provider != surveycore.ProviderCredamo || len(state.Definition.Questions) != 2 {
		t.Fatalf("state = %#v", state)
	}

	configState, err := service.BuildDefaultConfig(context.Background(), ParseSurveyRequest{URL: server.URL + "/s/demo_"})
	if err != nil {
		t.Fatal(err)
	}
	if configState.Config == nil || configState.Config.SurveyProvider != surveycore.ProviderCredamo || len(configState.Config.QuestionEntries) != 2 {
		t.Fatalf("configState = %#v", configState)
	}
}

func TestAppServiceRunSurveySubmitsTencentAndEvents(t *testing.T) {
	server := newAppTencentServer(t)
	defer server.Close()
	service := &AppService{survey: surveycore.New(surveycore.WithHTTPClient(rewriteTencentClient(server.URL)))}
	state, err := service.RunSurvey(context.Background(), RunSurveyRequest{
		Config: surveycore.RuntimeConfig{
			URL:            "https://wj.qq.com/s2/123/hashvalue/",
			SurveyProvider: surveycore.ProviderQQ,
			Target:         1,
		},
	})
	if err != nil {
		t.Fatalf("err = %v", err)
	}
	if state.Result == nil || state.Result.Success != 1 || len(state.Events) == 0 {
		t.Fatalf("state = %#v", state)
	}
}

func TestAppServiceStartRunStoresTaskState(t *testing.T) {
	server := newAppCredamoRunServer(t)
	defer server.Close()
	service := NewAppService()
	configState, err := service.BuildDefaultConfig(context.Background(), ParseSurveyRequest{URL: server.URL + "/s/demo_"})
	if err != nil {
		t.Fatal(err)
	}
	configState.Config.Target = 1

	state, err := service.StartRun(context.Background(), RunSurveyRequest{Config: *configState.Config})
	if err != nil {
		t.Fatal(err)
	}
	if !state.Running || state.StartedAt.IsZero() {
		t.Fatalf("initial state = %#v", state)
	}
	final := waitAppRun(t, service)
	if final.Running || final.Result == nil || final.Result.Success != 1 || len(final.Events) == 0 {
		t.Fatalf("final state = %#v", final)
	}
}

func TestAppServiceCancelRunMarksCanceling(t *testing.T) {
	service := NewAppService()
	state, err := service.StartRun(context.Background(), RunSurveyRequest{Config: surveycore.RuntimeConfig{
		URL:            "https://wj.qq.com/s2/123/hashvalue/",
		SurveyProvider: surveycore.ProviderQQ,
		Target:         1,
	}})
	if err != nil {
		t.Fatal(err)
	}
	if !state.Running {
		t.Fatalf("initial state = %#v", state)
	}
	state, err = service.CancelRun(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if !state.Canceling && state.Running {
		t.Fatalf("cancel state = %#v", state)
	}
}

func TestAppServiceSettingsRoundTripUsesConfigHome(t *testing.T) {
	t.Setenv("SURVEYCONTROLLER_CONFIG_HOME", t.TempDir())
	service := NewAppService()

	settings, err := service.GetAppSettings()
	if err != nil {
		t.Fatal(err)
	}
	settings.ThemeMode = "dark"
	settings.ShowNavigationText = false
	settings.AutosaveLogCount = 10

	saved, err := service.SaveAppSettings(context.Background(), SaveSettingsRequest{Settings: settings})
	if err != nil {
		t.Fatal(err)
	}
	loaded, err := service.GetAppSettings()
	if err != nil {
		t.Fatal(err)
	}
	if loaded.ThemeMode != "dark" || loaded.ShowNavigationText || saved.AutosaveLogCount != 10 {
		t.Fatalf("settings = %#v saved = %#v", loaded, saved)
	}
}

func TestAppServiceConfigRoundTrip(t *testing.T) {
	t.Setenv("SURVEYCONTROLLER_CONFIG_HOME", t.TempDir())
	service := NewAppService()

	state, err := service.SaveConfig(context.Background(), SaveConfigRequest{
		Config: surveycore.RuntimeConfig{
			URL:                   "https://wj.qq.com/s2/123/hash/",
			SurveyTitle:           "腾讯配置",
			SurveyProvider:        surveycore.ProviderQQ,
			Target:                6,
			Threads:               2,
			RandomIPEnabled:       true,
			ReverseFillEnabled:    true,
			ReverseFillSourcePath: "D:/demo.xlsx",
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if state.Path == "" || !strings.HasSuffix(filepath.Base(state.Path), ".json") {
		t.Fatalf("state = %#v", state)
	}

	loaded, err := service.LoadConfig(context.Background(), LoadConfigRequest{Path: state.Path})
	if err != nil {
		t.Fatal(err)
	}
	if loaded.Config == nil || loaded.Config.Target != 6 || !loaded.Config.RandomIPEnabled || !loaded.Config.ReverseFillEnabled {
		t.Fatalf("loaded = %#v", loaded)
	}
}

func TestAppServiceLoadDefaultConfigMissingReturnsEmpty(t *testing.T) {
	t.Setenv("SURVEYCONTROLLER_CONFIG_HOME", t.TempDir())
	service := NewAppService()

	state, err := service.LoadConfig(context.Background(), LoadConfigRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if state.Config == nil || state.Path == "" {
		t.Fatalf("state = %#v", state)
	}
}

func TestAppServicePreviewReverseFill(t *testing.T) {
	path := filepath.Join(t.TempDir(), "reverse.xlsx")
	file := excelize.NewFile()
	sheet := file.GetSheetName(0)
	_ = file.SetSheetRow(sheet, "A1", &[]any{"1、单选题", "2、文本题"})
	_ = file.SetSheetRow(sheet, "A2", &[]any{"B", "hello"})
	if err := file.SaveAs(path); err != nil {
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}

	service := NewAppService()
	preview, err := service.PreviewReverseFill(context.Background(), ReverseFillPreviewRequest{
		Path:     path,
		Format:   "wjx_text",
		StartRow: 1,
		Questions: []surveycore.QuestionMeta{
			{Num: 1, Title: "单选题", TypeCode: "3", OptionTexts: []string{"A", "B"}},
			{Num: 2, Title: "文本题", TypeCode: "1", TextInputs: 1},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(preview.SampleRows) != 1 || len(preview.SampleRows[0].Answers) != 2 {
		t.Fatalf("preview = %#v", preview)
	}
}

func newAppTencentServer(t *testing.T) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/v2/respondent/surveys/123/session":
			writeAppJSON(t, w, map[string]any{"code": "OK", "data": map[string]any{}})
		case "/api/v2/respondent/surveys/123/meta":
			writeAppJSON(t, w, map[string]any{"code": "OK", "data": map[string]any{"title": "腾讯标题 - 腾讯问卷"}})
		case "/api/v2/respondent/surveys/123/questions":
			writeAppJSON(t, w, map[string]any{
				"code": "OK",
				"data": map[string]any{
					"questions": []map[string]any{
						{"id": "q1", "type": "radio", "title": "单选", "page_id": "p1", "page": 1, "options": []map[string]any{{"id": "a", "text": "A"}, {"id": "b", "text": "B"}}},
						{"id": "q2", "type": "textarea", "title": "文本", "page_id": "p1", "page": 1},
					},
				},
			})
		case "/api/v2/respondent/surveys/123/answers":
			if r.Method != http.MethodPost {
				t.Fatalf("method = %s", r.Method)
			}
			var body map[string]any
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Fatalf("decode tencent submit body: %v", err)
			}
			if _, ok := body["answer_survey"].(map[string]any); !ok {
				t.Fatalf("answer_survey = %#v", body["answer_survey"])
			}
			writeAppJSON(t, w, map[string]any{"code": "OK", "data": map[string]any{"ok": true}})
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
}

func newAppCredamoServer(t *testing.T) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/survey/noauth/detail/get/demoano" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		writeAppJSON(t, w, map[string]any{
			"success": true,
			"data": map[string]any{
				"surveyTitle": "见数标题",
				"questions": []map[string]any{
					{"qstNo": "Q1", "qstTitle": "单选", "questionType": 2, "selector": 1, "questionId": "q1", "choices": []map[string]any{{"display": "A"}, {"display": "B"}}},
					{"qstNo": "Q2", "qstTitle": "文本", "questionType": 1, "questionId": "q2"},
				},
			},
		})
	}))
}

func newAppCredamoRunServer(t *testing.T) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/survey/noauth/detail/get/demoano":
			writeAppJSON(t, w, map[string]any{
				"success": true,
				"data": map[string]any{
					"surveyTitle": "见数标题",
					"questions": []map[string]any{
						{"qstNo": "Q1", "qstTitle": "单选", "questionType": 2, "selector": 1, "qstId": 101, "choices": []map[string]any{{"choiceId": 1, "display": "A"}, {"choiceId": 2, "display": "B"}}},
					},
				},
			})
		case "/v1/survey/answer/noauth/init/demoano":
			writeAppJSON(t, w, map[string]any{
				"success": true,
				"data": map[string]any{
					"answerToken": "token-1",
					"timestamp":   1700000000000,
				},
			})
		case "/v1/survey/answer/noauth/save":
			writeAppJSON(t, w, map[string]any{"success": true, "data": map[string]any{"ok": true}})
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
}

func waitAppRun(t *testing.T, service *AppService) RunTaskState {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		state := service.GetRunTaskState()
		if !state.Running {
			return state
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("run did not finish")
	return RunTaskState{}
}

func rewriteTencentClient(baseURL string) *http.Client {
	return &http.Client{
		Transport: rewriteTencentTransport{baseURL: baseURL, next: http.DefaultTransport},
	}
}

type rewriteTencentTransport struct {
	baseURL string
	next    http.RoundTripper
}

func (t rewriteTencentTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	if req.URL.Host == "wj.qq.com" {
		rewritten, err := http.NewRequestWithContext(req.Context(), req.Method, strings.Replace(req.URL.String(), "https://wj.qq.com", t.baseURL, 1), req.Body)
		if err != nil {
			return nil, err
		}
		rewritten.Header = req.Header.Clone()
		req = rewritten
	}
	return t.next.RoundTrip(req)
}

func writeAppJSON(t *testing.T, w http.ResponseWriter, value any) {
	t.Helper()
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(value); err != nil {
		t.Fatal(err)
	}
}
