package proxycore

import (
	"net"
	"net/url"
	"strings"
	"time"
)

const defaultProxySource = "custom"

type ProxyLease struct {
	Address  string
	ExpireAt string
	ExpireTS float64
	Poolable bool
	Source   string
}

func NormalizeProxyAddress(proxyAddress string) (string, bool) {
	normalized := strings.TrimSpace(proxyAddress)
	if normalized == "" {
		return "", false
	}
	if !strings.Contains(normalized, "://") {
		normalized = "http://" + normalized
	}
	return normalized, true
}

func BuildProxyLease(proxyAddress string, expireAt string, poolable bool, source string) (ProxyLease, bool) {
	normalized, ok := NormalizeProxyAddress(proxyAddress)
	if !ok {
		return ProxyLease{}, false
	}
	cleanSource := strings.TrimSpace(source)
	if cleanSource == "" {
		cleanSource = defaultProxySource
	}
	cleanExpireAt := strings.TrimSpace(expireAt)
	return ProxyLease{
		Address:  normalized,
		ExpireAt: cleanExpireAt,
		ExpireTS: ParseExpireAtToUnix(cleanExpireAt),
		Poolable: poolable,
		Source:   cleanSource,
	}, true
}

func ParseExpireAtToUnix(expireAt string) float64 {
	text := strings.TrimSpace(expireAt)
	if text == "" {
		return 0
	}
	layouts := []string{
		time.RFC3339Nano,
		time.RFC3339,
		"2006-01-02T15:04:05",
		"2006-01-02 15:04:05",
	}
	for _, layout := range layouts {
		parsed, err := time.Parse(layout, text)
		if err == nil {
			return float64(parsed.UTC().Unix())
		}
	}
	return 0
}

func ProxyLeaseHasSufficientTTL(lease ProxyLease, requiredTTL time.Duration, now time.Time) bool {
	if strings.TrimSpace(lease.Address) == "" {
		return false
	}
	if lease.ExpireTS <= 0 {
		return true
	}
	remaining := time.Unix(int64(lease.ExpireTS), 0).Sub(now)
	return remaining >= requiredTTL
}

func MaskProxyForLog(proxyAddress string) string {
	text := strings.TrimSpace(proxyAddress)
	if text == "" {
		return ""
	}
	candidate := text
	if !strings.Contains(candidate, "://") {
		candidate = "http://" + candidate
	}
	if parsed, err := url.Parse(candidate); err == nil {
		host := parsed.Hostname()
		port := parsed.Port()
		if host != "" {
			return formatHostPort(host, port)
		}
	}
	raw := text
	if idx := strings.Index(raw, "://"); idx >= 0 {
		raw = raw[idx+3:]
	}
	if idx := strings.Index(raw, "/"); idx >= 0 {
		raw = raw[:idx]
	}
	if idx := strings.LastIndex(raw, "@"); idx >= 0 {
		raw = raw[idx+1:]
	}
	return raw
}

func formatHostPort(host string, port string) string {
	if port == "" {
		return host
	}
	if strings.Contains(host, ":") && !strings.HasPrefix(host, "[") {
		return net.JoinHostPort(host, port)
	}
	return host + ":" + port
}
