package configio

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"surveycontroller/surveycore"
)

func TestConfigRoundTripKeepsRuntimeAndReverseFillFields(t *testing.T) {
	cfg := surveycore.RuntimeConfig{
		URL:                   "https://wj.qq.com/s2/123/hash/",
		SurveyTitle:           "腾讯测试",
		SurveyProvider:        surveycore.ProviderQQ,
		Target:                12,
		Threads:               4,
		SubmitInterval:        [2]int{1, 3},
		AnswerDuration:        [2]int{80, 120},
		RandomIPEnabled:       true,
		ProxySource:           "custom",
		CustomProxyAPI:        "https://proxy.example",
		RandomUAEnabled:       true,
		RandomUARatios:        map[string]int{"wechat": 50, "mobile": 30, "pc": 20},
		ReverseFillEnabled:    true,
		ReverseFillSourcePath: "D:/demo.xlsx",
		ReverseFillFormat:     ReverseFillFormatWJXSequence,
		ReverseFillStartRow:   3,
		ReverseFillThreads:    2,
		DimensionGroups:       []string{"服务", "价格"},
	}
	payload := SerializeRuntimeConfig(cfg)
	restored, err := DeserializeRuntimeConfig(payload)
	if err != nil {
		t.Fatal(err)
	}
	if restored.SurveyProvider != surveycore.ProviderQQ || restored.Target != 12 || !restored.RandomIPEnabled {
		t.Fatalf("restored = %#v", restored)
	}
	if !restored.ReverseFillEnabled || restored.ReverseFillFormat != ReverseFillFormatWJXSequence || restored.ReverseFillStartRow != 3 {
		t.Fatalf("reverse fill = %#v", restored)
	}
	if restored.RandomUARatios["wechat"] != 50 || len(restored.DimensionGroups) != 2 {
		t.Fatalf("settings = %#v", restored)
	}
}

func TestNormalizeRuntimeConfigPayloadBoundaries(t *testing.T) {
	cfg, err := DeserializeRuntimeConfig(map[string]any{
		"url":                    "https://www.wjx.cn/vm/demo.aspx",
		"target":                 "bad",
		"threads":                "4",
		"submit_interval":        []any{"1", "3"},
		"answer_duration":        []any{"90", "90"},
		"random_ip_enabled":      "yes",
		"proxy_source":           "bad",
		"random_ua_ratios":       map[string]any{"wechat": 20, "mobile": 20, "pc": 20},
		"reverse_fill_format":    "bad",
		"reverse_fill_start_row": "-2",
		"reverse_fill_threads":   "0",
		"dimension_groups":       []any{"服务", "服务", "未分组"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Target != 1 || cfg.Threads != 4 || cfg.SubmitInterval != [2]int{1, 3} {
		t.Fatalf("numeric fields = %#v", cfg)
	}
	if cfg.AnswerDuration != [2]int{81, 99} {
		t.Fatalf("duration = %#v", cfg.AnswerDuration)
	}
	if cfg.ProxySource != "default" || cfg.RandomUARatios["pc"] != 34 {
		t.Fatalf("proxy/ua = %#v", cfg)
	}
	if cfg.ReverseFillFormat != ReverseFillFormatAuto || cfg.ReverseFillStartRow != 1 || cfg.ReverseFillThreads != 4 {
		t.Fatalf("reverse fill = %#v", cfg)
	}
	if len(cfg.DimensionGroups) != 1 || cfg.DimensionGroups[0] != "服务" {
		t.Fatalf("dimension groups = %#v", cfg.DimensionGroups)
	}
}

func TestLoadSaveConfigWithComments(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "config.json")
	if _, err := Save(surveycore.RuntimeConfig{URL: "https://example.test", Target: 9}, path); err != nil {
		t.Fatal(err)
	}
	loaded, err := Load(path, true)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.Target != 9 {
		t.Fatalf("loaded = %#v", loaded)
	}

	commented := filepath.Join(t.TempDir(), "commented.json")
	if err := os.WriteFile(commented, []byte(`{"url":"https://example.com/a//b", // keep URL
"target":"7"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	loaded, err = Load(commented, true)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.Target != 7 {
		t.Fatalf("commented = %#v", loaded)
	}
}

func TestRejectUnknownFields(t *testing.T) {
	_, err := DeserializeRuntimeConfig(map[string]any{"url": "https://example.test", "random_proxy_api": "old"})
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestBuildDefaultConfigFilename(t *testing.T) {
	if got := BuildDefaultConfigFilename(`问卷 / 标题`); got != "问卷__标题.json" {
		t.Fatalf("filename = %s", got)
	}
}

func TestSerializeRuntimeConfigProducesJSON(t *testing.T) {
	payload := SerializeRuntimeConfig(surveycore.RuntimeConfig{URL: "https://example.test"})
	if _, err := json.Marshal(payload); err != nil {
		t.Fatal(err)
	}
}
