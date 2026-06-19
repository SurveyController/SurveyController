package proxycore

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
)

func (c *OfficialClient) parseExtractPayload(ctx context.Context, payload map[string]any, request OfficialExtractRequest) (OfficialExtractResult, error) {
	updatedSession, err := c.sessionManager.ApplyQuotaPayload(ctx, payload)
	if err != nil {
		return OfficialExtractResult{}, err
	}
	result := OfficialExtractResult{
		RequestedCount: request.Num,
		ReturnedCount:  1,
		Provider:       normalizeExtractProvider(payload["provider"]),
		Quota:          normalizeQuotaSnapshot(updatedSession),
		QuotaCost:      nonNegativeFloat(payload["quota_cost"], 0),
		QuotaCostTotal: nonNegativeFloat(payload["quota_cost_total"], 0),
	}
	if rawItems, ok := payload["items"].([]any); ok {
		for _, raw := range rawItems {
			rawMap, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			item, ok := parseOfficialProxyItem(rawMap)
			if ok {
				result.Items = append(result.Items, item)
			}
		}
		if len(result.Items) == 0 {
			return OfficialExtractResult{}, RandomIPError{Detail: "invalid_response"}
		}
		result.RequestedCount = positiveInt(payload["requested_count"], request.Num)
		result.ReturnedCount = min(nonNegativeInt(payload["returned_count"], len(result.Items)), len(result.Items))
		return result, nil
	}
	item, ok := parseOfficialProxyItem(payload)
	if !ok {
		return OfficialExtractResult{}, RandomIPError{Detail: "invalid_response"}
	}
	result.Items = []OfficialProxyItem{item}
	result.ReturnedCount = 1
	return result, nil
}

func parseSessionPayload(payload map[string]any, deviceID string, fallback RandomIPSession) (RandomIPSession, error) {
	userID := nonNegativeInt(payload["user_id"], 0)
	if userID <= 0 {
		return RandomIPSession{}, RandomIPError{Detail: "invalid_response:user_id_invalid"}
	}
	quota, known := resolveQuotaFromPayload(payload, fallback)
	return RandomIPSession{
		DeviceID:       strings.TrimSpace(deviceID),
		UserID:         userID,
		RemainingQuota: quota.RemainingQuota,
		TotalQuota:     quota.TotalQuota,
		UsedQuota:      quota.UsedQuota,
		QuotaKnown:     known,
	}, nil
}

func parseOfficialProxyItem(payload map[string]any) (OfficialProxyItem, bool) {
	host := strings.TrimSpace(stringValue(payload["host"]))
	port := nonNegativeInt(payload["port"], 0)
	account := strings.TrimSpace(stringValue(payload["account"]))
	password := strings.TrimSpace(stringValue(payload["password"]))
	if host == "" || port <= 0 || account == "" || password == "" {
		return OfficialProxyItem{}, false
	}
	return OfficialProxyItem{
		Host:     host,
		Port:     port,
		Account:  account,
		Password: password,
		ExpireAt: strings.TrimSpace(stringValue(payload["expire_at"])),
	}, true
}

func parseErrorPayload(response *http.Response, responseBody []byte) RandomIPError {
	retryAfter, _ := strconv.Atoi(strings.TrimSpace(response.Header.Get("Retry-After")))
	detail := ""
	var payload map[string]any
	if err := json.Unmarshal(responseBody, &payload); err == nil && payload != nil {
		detail = strings.TrimSpace(stringValue(payload["detail"]))
		retryAfter = max(retryAfter, nonNegativeInt(payload["retry_after_seconds"], retryAfter))
	}
	if detail == "" {
		detail = fmt.Sprintf("http_%d", response.StatusCode)
	}
	return RandomIPError{Detail: detail, StatusCode: response.StatusCode, RetryAfterSeconds: retryAfter}
}

func BuildOfficialProxyLease(item OfficialProxyItem, source string) (ProxyLease, bool) {
	host := strings.TrimSpace(item.Host)
	if host == "" || item.Port <= 0 {
		return ProxyLease{}, false
	}
	raw := fmt.Sprintf("%s:%d", host, item.Port)
	account := strings.TrimSpace(item.Account)
	password := strings.TrimSpace(item.Password)
	if account != "" && password != "" {
		raw = account + ":" + password + "@" + raw
	}
	poolable := strings.TrimSpace(item.ExpireAt) != ""
	return BuildProxyLease(raw, item.ExpireAt, poolable, source)
}

func normalizeExtractRequest(request OfficialExtractRequest) OfficialExtractRequest {
	if request.Minute <= 0 {
		request.Minute = 1
	}
	if request.Pool == "" {
		request.Pool = OfficialPoolQuality
	}
	request.Pool = strings.TrimSpace(request.Pool)
	request.Area = strings.TrimSpace(request.Area)
	if request.Num <= 0 {
		request.Num = 1
	}
	request.Upstream = strings.ToLower(strings.TrimSpace(request.Upstream))
	if request.Upstream == "" {
		request.Upstream = OfficialUpstreamDefault
	}
	return request
}

func normalizeExtractProvider(value any) string {
	provider := strings.ToLower(strings.TrimSpace(stringValue(value)))
	if provider == OfficialUpstreamDefault || provider == OfficialUpstreamBenefit {
		return provider
	}
	return ""
}

func stringValue(value any) string {
	switch item := value.(type) {
	case nil:
		return ""
	case string:
		return item
	case json.Number:
		return item.String()
	default:
		return fmt.Sprint(item)
	}
}

func boolValue(value any) bool {
	switch item := value.(type) {
	case bool:
		return item
	case string:
		switch strings.ToLower(strings.TrimSpace(item)) {
		case "1", "true", "yes", "on":
			return true
		default:
			return false
		}
	case float64:
		return item != 0
	default:
		return false
	}
}

func endpointOrDefault(value string, fallback string) string {
	cleaned := strings.TrimSpace(value)
	if cleaned == "" {
		return fallback
	}
	return cleaned
}

func cloneHeaders(headers map[string]string) map[string]string {
	cloned := make(map[string]string, len(headers))
	for key, value := range headers {
		cloned[key] = value
	}
	return cloned
}

func defaultOfficialHeaders() map[string]string {
	return map[string]string{
		"User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
		"Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
		"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
		"Connection":      "close",
	}
}
