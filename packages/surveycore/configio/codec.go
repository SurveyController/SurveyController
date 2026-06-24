package configio

import (
	"encoding/json"
	"fmt"
	"math"
	"strings"

	"surveycontroller/surveycore"
	"surveycontroller/surveycore/internal/model"
)

const (
	ReverseFillFormatAuto        = "auto"
	ReverseFillFormatWJXSequence = "wjx_sequence"
	ReverseFillFormatWJXScore    = "wjx_score"
	ReverseFillFormatWJXText     = "wjx_text"
)

var supportedReverseFillFormats = map[string]bool{
	ReverseFillFormatAuto:        true,
	ReverseFillFormatWJXSequence: true,
	ReverseFillFormatWJXScore:    true,
	ReverseFillFormatWJXText:     true,
}

var allowedRuntimeConfigFields = map[string]bool{
	"url":                      true,
	"survey_title":             true,
	"survey_provider":          true,
	"target":                   true,
	"threads":                  true,
	"submit_interval":          true,
	"answer_duration":          true,
	"answer_datetime_window":   true,
	"random_ip_enabled":        true,
	"proxy_source":             true,
	"custom_proxy_api":         true,
	"proxy_area_code":          true,
	"random_ua_enabled":        true,
	"random_ua_ratios":         true,
	"fail_stop_enabled":        true,
	"pause_on_aliyun_captcha":  true,
	"reliability_mode_enabled": true,
	"psycho_target_alpha":      true,
	"ai_mode":                  true,
	"ai_provider":              true,
	"ai_api_key":               true,
	"ai_base_url":              true,
	"ai_api_protocol":          true,
	"ai_model":                 true,
	"ai_system_prompt":         true,
	"reverse_fill_enabled":     true,
	"reverse_fill_source_path": true,
	"reverse_fill_format":      true,
	"reverse_fill_start_row":   true,
	"reverse_fill_threads":     true,
	"answer_rules":             true,
	"dimension_groups":         true,
	"question_entries":         true,
	"questions_info":           true,
}

func SerializeRuntimeConfig(config surveycore.RuntimeConfig) map[string]any {
	data, _ := json.Marshal(config)
	var payload map[string]any
	_ = json.Unmarshal(data, &payload)
	return payload
}

func DeserializeRuntimeConfig(payload map[string]any) (surveycore.RuntimeConfig, error) {
	if err := rejectUnknownKeys(payload); err != nil {
		return surveycore.RuntimeConfig{}, err
	}
	normalized := NormalizeRuntimeConfigPayload(payload)
	data, err := json.Marshal(normalized)
	if err != nil {
		return surveycore.RuntimeConfig{}, err
	}
	var cfg surveycore.RuntimeConfig
	if err := json.Unmarshal(data, &cfg); err != nil {
		return surveycore.RuntimeConfig{}, err
	}
	return cfg, nil
}

func NormalizeRuntimeConfigPayload(raw map[string]any) map[string]any {
	out := map[string]any{}
	for key, value := range raw {
		out[key] = value
	}
	out["url"] = strings.TrimSpace(stringValue(raw["url"]))
	out["survey_title"] = stringValue(raw["survey_title"])
	out["survey_provider"] = normalizeProvider(raw["survey_provider"], out["url"])
	out["target"] = positiveInt(raw["target"], 1)
	out["threads"] = positiveInt(raw["threads"], 1)
	out["submit_interval"] = intPair(raw["submit_interval"], [2]int{0, 0})
	out["answer_duration"] = normalizeAnswerDuration(raw["answer_duration"])
	out["answer_datetime_window"] = model.NormalizeAnswerDatetimeWindow(stringPair(raw["answer_datetime_window"]))
	out["random_ip_enabled"] = boolValue(raw["random_ip_enabled"], false)
	out["proxy_source"] = normalizeProxySource(raw["proxy_source"])
	out["custom_proxy_api"] = strings.TrimSpace(stringValue(raw["custom_proxy_api"]))
	if raw["proxy_area_code"] != nil {
		area := strings.TrimSpace(stringValue(raw["proxy_area_code"]))
		if area != "" {
			out["proxy_area_code"] = area
		}
	}
	out["random_ua_enabled"] = boolValue(raw["random_ua_enabled"], false)
	out["random_ua_ratios"] = normalizeRandomUARatios(raw["random_ua_ratios"])
	out["fail_stop_enabled"] = boolValue(raw["fail_stop_enabled"], true)
	out["pause_on_aliyun_captcha"] = boolValue(raw["pause_on_aliyun_captcha"], true)
	out["reliability_mode_enabled"] = boolValue(raw["reliability_mode_enabled"], true)
	out["psycho_target_alpha"] = normalizeTargetAlpha(raw["psycho_target_alpha"])
	out["ai_mode"] = normalizeAIMode(raw["ai_mode"])
	out["ai_provider"] = defaultString(raw["ai_provider"], "deepseek")
	out["ai_api_key"] = stringValue(raw["ai_api_key"])
	out["ai_base_url"] = stringValue(raw["ai_base_url"])
	out["ai_api_protocol"] = defaultString(raw["ai_api_protocol"], "auto")
	out["ai_model"] = stringValue(raw["ai_model"])
	out["ai_system_prompt"] = stringValue(raw["ai_system_prompt"])
	out["reverse_fill_enabled"] = boolValue(raw["reverse_fill_enabled"], false)
	out["reverse_fill_source_path"] = stringValue(raw["reverse_fill_source_path"])
	out["reverse_fill_format"] = normalizeReverseFillFormat(raw["reverse_fill_format"])
	out["reverse_fill_start_row"] = positiveInt(raw["reverse_fill_start_row"], 1)
	out["reverse_fill_threads"] = positiveInt(raw["reverse_fill_threads"], positiveInt(raw["threads"], 1))
	out["dimension_groups"] = normalizeStringList(raw["dimension_groups"])
	if _, ok := raw["answer_rules"]; !ok {
		out["answer_rules"] = []map[string]any{}
	}
	if _, ok := raw["question_entries"]; !ok {
		out["question_entries"] = []surveycore.QuestionEntry{}
	}
	if _, ok := raw["questions_info"]; !ok {
		out["questions_info"] = []surveycore.QuestionMeta{}
	}
	return out
}

func rejectUnknownKeys(payload map[string]any) error {
	for key := range payload {
		if !allowedRuntimeConfigFields[key] {
			return fmt.Errorf("该配置文件损坏：配置包含不支持的字段（%s）", key)
		}
	}
	return nil
}

func normalizeProvider(raw any, rawURL any) string {
	text := strings.ToLower(strings.TrimSpace(stringValue(raw)))
	switch text {
	case surveycore.ProviderWJX, surveycore.ProviderQQ, surveycore.ProviderCredamo:
		return text
	}
	url := strings.ToLower(strings.TrimSpace(stringValue(rawURL)))
	switch {
	case strings.Contains(url, "wj.qq.com"):
		return surveycore.ProviderQQ
	case strings.Contains(url, "credamo"):
		return surveycore.ProviderCredamo
	default:
		return surveycore.ProviderWJX
	}
}

func normalizeProxySource(raw any) string {
	switch strings.ToLower(strings.TrimSpace(stringValue(raw))) {
	case "default", "benefit", "custom":
		return strings.ToLower(strings.TrimSpace(stringValue(raw)))
	default:
		return "default"
	}
}

func normalizeAIMode(raw any) string {
	if strings.ToLower(strings.TrimSpace(stringValue(raw))) == "provider" {
		return "provider"
	}
	return "free"
}

func normalizeReverseFillFormat(raw any) string {
	text := strings.ToLower(strings.TrimSpace(stringValue(raw)))
	if supportedReverseFillFormats[text] {
		return text
	}
	return ReverseFillFormatAuto
}

func normalizeTargetAlpha(raw any) float64 {
	value := floatValue(raw, 0.85)
	if value <= 0 || math.IsNaN(value) || math.IsInf(value, 0) {
		return 0.85
	}
	if value > 1 {
		return 1
	}
	return value
}

func normalizeRandomUARatios(raw any) map[string]int {
	defaults := map[string]int{"wechat": 33, "mobile": 33, "pc": 34}
	mapped, ok := raw.(map[string]any)
	if !ok {
		if typed, ok := raw.(map[string]int); ok {
			sum := typed["wechat"] + typed["mobile"] + typed["pc"]
			if sum == 100 && typed["wechat"] >= 0 && typed["mobile"] >= 0 && typed["pc"] >= 0 {
				return map[string]int{"wechat": typed["wechat"], "mobile": typed["mobile"], "pc": typed["pc"]}
			}
		}
		return defaults
	}
	result := map[string]int{}
	sum := 0
	for _, key := range []string{"wechat", "mobile", "pc"} {
		value := intValue(mapped[key], -1)
		if value < 0 || value > 100 {
			return defaults
		}
		result[key] = value
		sum += value
	}
	if sum != 100 {
		return defaults
	}
	return result
}

func normalizeStringList(raw any) []string {
	items, ok := raw.([]any)
	if !ok {
		return nil
	}
	result := make([]string, 0, len(items))
	seen := map[string]struct{}{}
	for _, item := range items {
		text := strings.TrimSpace(stringValue(item))
		if text == "" || text == "未分组" {
			continue
		}
		if _, exists := seen[text]; exists {
			continue
		}
		seen[text] = struct{}{}
		result = append(result, text)
	}
	return result
}

func normalizeAnswerDuration(raw any) [2]int {
	pair := intPair(raw, [2]int{60, 120})
	if pair[0] == 0 && pair[1] == 0 {
		return [2]int{60, 120}
	}
	if pair[0] == pair[1] {
		return legacyDuration(pair[0])
	}
	if pair[1] < pair[0] {
		pair[1] = pair[0]
	}
	pair[0] = minInt(pair[0], 1800)
	pair[1] = minInt(pair[1], 1800)
	return pair
}

func legacyDuration(seconds int) [2]int {
	if seconds <= 0 {
		return [2]int{60, 120}
	}
	seconds = minInt(seconds, 1800)
	low := int(math.Round(float64(seconds) * 0.9))
	high := int(math.Round(float64(seconds) * 1.1))
	return [2]int{low, minInt(high, 1800)}
}
