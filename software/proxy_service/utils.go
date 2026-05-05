package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

func normalizeProxySource(source string) string {
	switch strings.ToLower(strings.TrimSpace(source)) {
	case sourceBenefit:
		return sourceBenefit
	case sourceCustom:
		return sourceCustom
	default:
		return sourceDefault
	}
}

func normalizeAreaCode(code string) string {
	code = strings.TrimSpace(code)
	if len(code) != 6 {
		return ""
	}
	for _, ch := range code {
		if ch < '0' || ch > '9' {
			return ""
		}
	}
	return code
}

func normalizeProxyAddress(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	if !strings.Contains(value, "://") {
		return "http://" + value
	}
	return value
}

func parseExpireAtToTS(expireAt string) float64 {
	expireAt = strings.TrimSpace(expireAt)
	if expireAt == "" {
		return 0
	}
	parsed, err := time.Parse(time.RFC3339, expireAt)
	if err != nil {
		return 0
	}
	return float64(parsed.UTC().Unix())
}

func buildProxyLease(proxyAddress, expireAt string, poolable bool, source string) *proxyLease {
	normalized := normalizeProxyAddress(proxyAddress)
	if normalized == "" {
		return nil
	}
	expireAt = strings.TrimSpace(expireAt)
	return &proxyLease{
		Address:  normalized,
		ExpireAt: expireAt,
		ExpireTS: parseExpireAtToTS(expireAt),
		Poolable: poolable,
		Source:   strings.TrimSpace(source),
	}
}

func coerceProxyLease(value any, source string) *proxyLease {
	switch item := value.(type) {
	case proxyLease:
		copyValue := item
		copyValue.Address = normalizeProxyAddress(copyValue.Address)
		if copyValue.Address == "" {
			return nil
		}
		return &copyValue
	case *proxyLease:
		if item == nil {
			return nil
		}
		copyValue := *item
		copyValue.Address = normalizeProxyAddress(copyValue.Address)
		if copyValue.Address == "" {
			return nil
		}
		return &copyValue
	case string:
		return buildProxyLease(item, "", true, source)
	case map[string]any:
		address := strings.TrimSpace(stringValue(item["address"]))
		if address == "" {
			address = strings.TrimSpace(stringValue(item["proxy"]))
		}
		if address == "" {
			address = strings.TrimSpace(stringValue(item["host"]))
			port := intValue(item["port"], 0)
			if address != "" && port > 0 && !strings.Contains(address, ":") {
				address = fmt.Sprintf("%s:%d", address, port)
			}
		}
		poolable := boolValue(item["poolable"], true)
		itemSource := strings.TrimSpace(stringValue(item["source"]))
		if itemSource == "" {
			itemSource = source
		}
		return buildProxyLease(address, stringValue(item["expire_at"]), poolable, itemSource)
	default:
		return nil
	}
}

func requiredTTLSeconds(config proxyConfig) int {
	minute := config.OccupyMinute
	if minute <= 0 {
		minute = 1
	}
	return minute*60 + proxyTTLGraceSeconds
}

func hasSufficientTTL(lease *proxyLease, requiredTTLSeconds int) bool {
	if lease == nil {
		return false
	}
	if lease.ExpireTS <= 0 {
		return true
	}
	return (lease.ExpireTS - float64(time.Now().Unix())) >= float64(maxInt(requiredTTLSeconds, 0))
}

func stringValue(value any) string {
	switch item := value.(type) {
	case string:
		return item
	case fmt.Stringer:
		return item.String()
	case float64:
		return strconv.FormatFloat(item, 'f', -1, 64)
	case float32:
		return strconv.FormatFloat(float64(item), 'f', -1, 64)
	case int:
		return strconv.Itoa(item)
	case int64:
		return strconv.FormatInt(item, 10)
	case int32:
		return strconv.FormatInt(int64(item), 10)
	case json.Number:
		return item.String()
	case nil:
		return ""
	default:
		return fmt.Sprintf("%v", item)
	}
}

func intValue(value any, defaultValue int) int {
	switch item := value.(type) {
	case int:
		return item
	case int32:
		return int(item)
	case int64:
		return int(item)
	case float32:
		return int(item)
	case float64:
		return int(item)
	case json.Number:
		if parsed, err := item.Int64(); err == nil {
			return int(parsed)
		}
	case string:
		if parsed, err := strconv.Atoi(strings.TrimSpace(item)); err == nil {
			return parsed
		}
	}
	return defaultValue
}

func boolValue(value any, defaultValue bool) bool {
	switch item := value.(type) {
	case bool:
		return item
	case string:
		trimmed := strings.TrimSpace(strings.ToLower(item))
		if trimmed == "true" || trimmed == "1" {
			return true
		}
		if trimmed == "false" || trimmed == "0" {
			return false
		}
	case int:
		return item != 0
	case float64:
		return item != 0
	}
	return defaultValue
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func joinURL(baseURL, path string) string {
	baseURL = strings.TrimRight(strings.TrimSpace(baseURL), "/")
	path = "/" + strings.TrimLeft(strings.TrimSpace(path), "/")
	return baseURL + path
}

func writeJSON(w http.ResponseWriter, statusCode int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(statusCode)
	_ = json.NewEncoder(w).Encode(payload)
}

func readJSON(r *http.Request, target any) error {
	defer r.Body.Close()
	decoder := json.NewDecoder(io.LimitReader(r.Body, 1<<20))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	return nil
}
