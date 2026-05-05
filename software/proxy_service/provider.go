package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
)

func (svc *poolService) fetchProxyBatch(expectedCount int) ([]proxyLease, error) {
	cfg := svc.snapshotConfig()
	if normalizeProxySource(cfg.Source) == sourceCustom {
		return svc.fetchCustomProxyBatch(cfg, expectedCount)
	}
	return svc.fetchOfficialProxyBatch(cfg, expectedCount)
}

func (svc *poolService) fetchCustomProxyBatch(cfg proxyConfig, expectedCount int) ([]proxyLease, error) {
	urls, err := proxyAPICandidates(cfg.CustomAPIURL, expectedCount)
	if err != nil {
		return nil, err
	}
	var lastErr error
	for _, candidate := range urls {
		response, body, err := svc.httpGet(candidate, nil)
		if err != nil {
			lastErr = err
			continue
		}
		if response.StatusCode >= 400 {
			lastErr = &upstreamError{Message: fmt.Sprintf("代理接口 HTTP %d", response.StatusCode), StatusCode: response.StatusCode}
			continue
		}
		if fatal := extractCustomAPIError(body); fatal != "" {
			return nil, &upstreamError{Message: fatal, StatusCode: response.StatusCode}
		}
		addresses, err := parseProxyPayload(body)
		if err != nil {
			lastErr = err
			continue
		}
		leases := make([]proxyLease, 0, len(addresses))
		for _, address := range addresses {
			lease := buildProxyLease(address, "", true, sourceCustom)
			if lease != nil {
				leases = append(leases, *lease)
			}
		}
		if len(leases) == 0 {
			lastErr = errors.New("随机IP接口返回为空")
			continue
		}
		if len(leases) > expectedCount {
			leases = leases[:expectedCount]
		}
		return leases, nil
	}
	if lastErr == nil {
		lastErr = errors.New("获取随机IP失败")
	}
	return nil, lastErr
}

func (svc *poolService) fetchOfficialProxyBatch(cfg proxyConfig, expectedCount int) ([]proxyLease, error) {
	snapshot, err := svc.fetchSessionSnapshot()
	if err != nil {
		return nil, err
	}
	if !snapshot.Authenticated || snapshot.UserID <= 0 {
		return nil, &authError{Detail: "not_authenticated"}
	}
	minute := cfg.OccupyMinute
	if normalizeProxySource(cfg.Source) != sourceDefault {
		minute = 1
	}
	pool := resolveDefaultPoolByArea(cfg.AreaCode)
	if pool == "" {
		pool = "ordinary"
	}
	body := map[string]any{
		"user_id": snapshot.UserID,
		"minute":  minute,
		"pool":    pool,
	}
	upstream := getProxyUpstream(cfg.Source)
	body["upstream"] = upstream
	if expectedCount > 1 {
		body["num"] = expectedCount
	}
	if areaValue := resolveOfficialAreaRequestValue(cfg.Source, cfg.AreaCode); areaValue != "" {
		body["area"] = areaValue
	}
	response, payload, err := svc.httpPostJSON(joinURL(svc.baseURL, "/api/extract"), body, map[string]string{
		"Content-Type": "application/json",
	})
	if err != nil {
		return nil, err
	}
	if response.StatusCode >= 400 {
		detail := extractErrorDetail(payload)
		if detail == "" {
			detail = fmt.Sprintf("http_%d", response.StatusCode)
		}
		return nil, &authError{Detail: detail, StatusCode: response.StatusCode}
	}
	var raw any
	if err := json.Unmarshal(payload, &raw); err != nil {
		return nil, &authError{Detail: "invalid_response", StatusCode: response.StatusCode}
	}
	data, ok := raw.(map[string]any)
	if !ok {
		return nil, &authError{Detail: "invalid_response", StatusCode: response.StatusCode}
	}
	if isAreaQualityRetryPayload(data) {
		return nil, &upstreamError{Message: "当前地区IP质量差，建议切换其他地区", StatusCode: response.StatusCode}
	}
	if items, ok := data["items"].([]any); ok {
		leases := make([]proxyLease, 0, len(items))
		provider := resolveFinalSource(normalizeExtractProvider(data["provider"]), cfg.Source)
		for _, rawItem := range items {
			itemMap, ok := rawItem.(map[string]any)
			if !ok {
				continue
			}
			lease := buildDefaultProxyLease(itemMap, provider)
			if lease != nil {
				leases = append(leases, *lease)
			}
		}
		if len(leases) == 0 {
			return nil, &authError{Detail: "invalid_response", StatusCode: response.StatusCode}
		}
		if len(leases) > expectedCount {
			leases = leases[:expectedCount]
		}
		return leases, nil
	}
	provider := resolveFinalSource(normalizeExtractProvider(data["provider"]), cfg.Source)
	lease := buildDefaultProxyLease(data, provider)
	if lease == nil {
		return nil, &authError{Detail: "invalid_response", StatusCode: response.StatusCode}
	}
	return []proxyLease{*lease}, nil
}

func (svc *poolService) fetchSessionSnapshot() (*sessionSnapshot, error) {
	response, payload, err := svc.httpGet(joinURL(svc.baseURL, "/api/session"), nil)
	if err != nil {
		return nil, err
	}
	if response.StatusCode >= 400 {
		return nil, &authError{Detail: fmt.Sprintf("http_%d", response.StatusCode), StatusCode: response.StatusCode}
	}
	var snapshot sessionSnapshot
	if err := json.Unmarshal(payload, &snapshot); err != nil {
		return nil, err
	}
	return &snapshot, nil
}

func proxyAPICandidates(proxyURL string, expectedCount int) ([]string, error) {
	proxyURL = strings.TrimSpace(proxyURL)
	if proxyURL == "" {
		return nil, errors.New("自定义代理API地址不能为空，请先在设置中填写API地址")
	}
	if strings.Contains(proxyURL, "{num}") {
		return []string{strings.ReplaceAll(proxyURL, "{num}", strconv.Itoa(maxInt(expectedCount, 1)))}, nil
	}
	lower := strings.ToLower(proxyURL)
	if strings.Contains(lower, "num=") || strings.Contains(lower, "count=") {
		return []string{proxyURL}, nil
	}
	sep := "?"
	if strings.Contains(proxyURL, "?") {
		sep = "&"
	}
	return []string{
		fmt.Sprintf("%s%snum=%d", proxyURL, sep, maxInt(expectedCount, 1)),
		proxyURL,
	}, nil
}

func extractCustomAPIError(body []byte) string {
	var payload any
	if err := json.Unmarshal(body, &payload); err != nil {
		return ""
	}
	data, ok := payload.(map[string]any)
	if !ok {
		return ""
	}
	if intValue(data["code"], 0) == 0 {
		return ""
	}
	message := strings.TrimSpace(stringValue(data["message"]))
	if message == "" {
		return ""
	}
	for _, item := range fatalPatterns {
		if item.pattern.MatchString(message) {
			return item.userMsg
		}
	}
	return ""
}

func normalizeExtractProvider(value any) string {
	switch strings.ToLower(strings.TrimSpace(stringValue(value))) {
	case upstreamBenefit:
		return upstreamBenefit
	case upstreamDefault:
		return upstreamDefault
	default:
		return ""
	}
}

func resolveFinalSource(finalUpstream string, fallbackSource string) string {
	switch finalUpstream {
	case upstreamBenefit:
		return sourceBenefit
	case upstreamDefault:
		return sourceDefault
	default:
		return normalizeProxySource(fallbackSource)
	}
}

func getProxyUpstream(source string) string {
	if normalizeProxySource(source) == sourceBenefit {
		return upstreamBenefit
	}
	return upstreamDefault
}

func resolveDefaultPoolByArea(areaCode string) string {
	areaCode = normalizeAreaCode(areaCode)
	if areaCode == "" {
		return ""
	}
	if strings.HasSuffix(areaCode, "0000") {
		if _, ok := ordinaryPoolProvinceCodes[areaCode]; ok {
			return "ordinary"
		}
	}
	return "quality"
}

func resolveOfficialAreaRequestValue(source string, areaCode string) string {
	_ = source
	return normalizeAreaCode(areaCode)
}

func isAreaQualityRetryPayload(payload map[string]any) bool {
	return stringValue(payload["code"]) == "-1" &&
		stringValue(payload["status"]) == "200" &&
		strings.TrimSpace(stringValue(payload["message"])) == "请重试" &&
		payload["data"] == nil
}

func extractErrorDetail(body []byte) string {
	var payload any
	if err := json.Unmarshal(body, &payload); err != nil {
		return ""
	}
	data, ok := payload.(map[string]any)
	if !ok {
		return ""
	}
	return strings.TrimSpace(stringValue(data["detail"]))
}
