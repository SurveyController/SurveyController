package proxycore

import (
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
)

var proxyAddressRE = regexp.MustCompile(`(?i)(?:https?://)?(?:([^\s:@/,]+):([^\s:@/,]+)@)?((?:\d{1,3}\.){3}\d{1,3}):(\d{2,5})`)

var ErrNoProxyAddress = errors.New("proxy payload contains no valid proxy address")

func ParseProxyPayload(payload []byte) ([]string, error) {
	var decoded any
	if err := json.Unmarshal(payload, &decoded); err != nil {
		return nil, fmt.Errorf("parse proxy payload JSON: %w", err)
	}
	candidates := make([]string, 0)
	recursiveFindProxies(decoded, &candidates, 0)
	if len(candidates) == 0 {
		return nil, ErrNoProxyAddress
	}
	seen := make(map[string]struct{}, len(candidates))
	unique := make([]string, 0, len(candidates))
	for _, candidate := range candidates {
		if _, exists := seen[candidate]; exists {
			continue
		}
		seen[candidate] = struct{}{}
		unique = append(unique, candidate)
	}
	return unique, nil
}

func ParseProxyLeases(payload []byte, source string) ([]ProxyLease, error) {
	addresses, err := ParseProxyPayload(payload)
	if err != nil {
		return nil, err
	}
	leases := make([]ProxyLease, 0, len(addresses))
	for _, address := range addresses {
		lease, ok := BuildProxyLease(address, "", true, source)
		if ok {
			leases = append(leases, lease)
		}
	}
	if len(leases) == 0 {
		return nil, ErrNoProxyAddress
	}
	return leases, nil
}

func recursiveFindProxies(value any, results *[]string, depth int) {
	if depth > 10 {
		return
	}
	switch item := value.(type) {
	case map[string]any:
		if proxy, ok := extractProxyFromMap(item); ok {
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
		if proxy, ok := ExtractProxyFromString(item); ok {
			*results = append(*results, proxy)
		}
	}
}

func extractProxyFromMap(value map[string]any) (string, bool) {
	ip := firstStringValue(value, "ip", "IP", "host")
	port := firstStringValue(value, "port", "Port", "PORT")
	if ip != "" && port != "" {
		username := firstStringValue(value, "account", "username", "user")
		password := firstStringValue(value, "password", "pwd", "pass")
		if username != "" && password != "" {
			return username + ":" + password + "@" + ip + ":" + port, true
		}
		return ip + ":" + port, true
	}
	for _, child := range value {
		text, ok := child.(string)
		if !ok {
			continue
		}
		if proxy, found := ExtractProxyFromString(text); found {
			return proxy, true
		}
	}
	return "", false
}

func firstStringValue(value map[string]any, keys ...string) string {
	for _, key := range keys {
		raw, ok := value[key]
		if !ok {
			continue
		}
		switch item := raw.(type) {
		case string:
			if cleaned := strings.TrimSpace(item); cleaned != "" {
				return cleaned
			}
		case float64:
			return strings.TrimRight(strings.TrimRight(fmt.Sprintf("%.0f", item), "0"), ".")
		case int:
			return fmt.Sprintf("%d", item)
		}
	}
	return ""
}

func ExtractProxyFromString(value string) (string, bool) {
	matches := proxyAddressRE.FindStringSubmatch(strings.TrimSpace(value))
	if len(matches) == 0 {
		return "", false
	}
	user := matches[1]
	password := matches[2]
	ip := matches[3]
	port := matches[4]
	if user != "" && password != "" {
		return user + ":" + password + "@" + ip + ":" + port, true
	}
	return ip + ":" + port, true
}
