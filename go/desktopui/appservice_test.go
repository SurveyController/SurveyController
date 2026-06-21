package main

import (
	"context"
	"errors"
	"path/filepath"
	"strings"
	"testing"

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

func TestAppServiceRunSurveyReturnsCoreErrorAndEvents(t *testing.T) {
	service := NewAppService()
	state, err := service.RunSurvey(context.Background(), RunSurveyRequest{
		Config: surveycore.RuntimeConfig{
			URL:            "https://wj.qq.com/s2/123/hashvalue/",
			SurveyProvider: surveycore.ProviderQQ,
			Target:         1,
		},
	})
	if !errors.Is(err, surveycore.ErrUnsupportedOperation) {
		t.Fatalf("err = %v", err)
	}
	if state.Result == nil || len(state.Events) != 1 {
		t.Fatalf("state = %#v", state)
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
