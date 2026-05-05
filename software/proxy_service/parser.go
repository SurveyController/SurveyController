package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

func parseProxyPayload(body []byte) ([]string, error) {
	var payload any
	if err := json.Unmarshal(body, &payload); err != nil {
		return nil, fmt.Errorf("JSON解析失败: %w", err)
	}
	results := make([]string, 0)
	recursiveFindProxies(payload, &results, 0)
	if len(results) == 0 {
		return nil, errors.New("返回数据中无有效代理地址")
	}
	seen := make(map[string]struct{}, len(results))
	unique := make([]string, 0, len(results))
	for _, address := range results {
		if _, ok := seen[address]; ok {
			continue
		}
		seen[address] = struct{}{}
		unique = append(unique, address)
	}
	return unique, nil
}

func recursiveFindProxies(value any, results *[]string, depth int) {
	if depth > 10 {
		return
	}
	switch item := value.(type) {
	case map[string]any:
		if proxy := extractProxyFromDict(item); proxy != "" {
			*results = append(*results, proxy)
			return
		}
		for _, child := range item {
			recursiveFindProxies(child, results, depth+1)
		}
	case []any:
		for _, child := range item {
			recursiveFindProxies(child, results, depth+1)
		}
	case string:
		if proxy := extractProxyFromString(item); proxy != "" {
			*results = append(*results, proxy)
		}
	}
}

func extractProxyFromString(text string) string {
	text = strings.TrimSpace(text)
	if text == "" {
		return ""
	}
	match := ipPortPattern.FindStringSubmatch(text)
	if len(match) != 5 {
		return ""
	}
	user := match[1]
	pass := match[2]
	ip := match[3]
	port := match[4]
	if user != "" && pass != "" {
		return fmt.Sprintf("%s:%s@%s:%s", user, pass, ip, port)
	}
	return fmt.Sprintf("%s:%s", ip, port)
}

func extractProxyFromDict(data map[string]any) string {
	ip := strings.TrimSpace(stringValue(data["ip"]))
	if ip == "" {
		ip = strings.TrimSpace(stringValue(data["IP"]))
	}
	if ip == "" {
		ip = strings.TrimSpace(stringValue(data["host"]))
	}
	port := strings.TrimSpace(stringValue(data["port"]))
	if port == "" {
		port = strings.TrimSpace(stringValue(data["Port"]))
	}
	if ip != "" && port != "" {
		username := strings.TrimSpace(stringValue(data["account"]))
		if username == "" {
			username = strings.TrimSpace(stringValue(data["username"]))
		}
		if username == "" {
			username = strings.TrimSpace(stringValue(data["user"]))
		}
		password := strings.TrimSpace(stringValue(data["password"]))
		if password == "" {
			password = strings.TrimSpace(stringValue(data["pwd"]))
		}
		if password == "" {
			password = strings.TrimSpace(stringValue(data["pass"]))
		}
		if username != "" && password != "" {
			return fmt.Sprintf("%s:%s@%s:%s", username, password, ip, port)
		}
		return fmt.Sprintf("%s:%s", ip, port)
	}
	for _, value := range data {
		if text, ok := value.(string); ok {
			if proxy := extractProxyFromString(text); proxy != "" {
				return proxy
			}
		}
	}
	return ""
}

func buildDefaultProxyLease(payload map[string]any, source string) *proxyLease {
	host := strings.TrimSpace(stringValue(payload["host"]))
	port := intValue(payload["port"], 0)
	if host == "" || port <= 0 {
		return nil
	}
	account := strings.TrimSpace(stringValue(payload["account"]))
	password := strings.TrimSpace(stringValue(payload["password"]))
	raw := fmt.Sprintf("%s:%d", host, port)
	if account != "" && password != "" {
		raw = fmt.Sprintf("%s:%s@%s:%d", account, password, host, port)
	}
	expireAt := strings.TrimSpace(stringValue(payload["expire_at"]))
	poolable := true
	if expireAt == "" {
		poolable = false
	}
	return buildProxyLease(raw, expireAt, poolable, source)
}
