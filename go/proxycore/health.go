package proxycore

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const DefaultHealthCheckURL = "https://www.baidu.com/generate_204"

type HealthCheckOptions struct {
	TargetURL  string
	HTTPClient *http.Client
	Timeout    time.Duration
}

type HealthCheckResult struct {
	Address    string
	TargetURL  string
	OK         bool
	StatusCode int
	Duration   time.Duration
	Error      string
}

func CheckProxyHealth(ctx context.Context, lease ProxyLease, options HealthCheckOptions) HealthCheckResult {
	started := time.Now()
	address := strings.TrimSpace(lease.Address)
	targetURL := strings.TrimSpace(options.TargetURL)
	if targetURL == "" {
		targetURL = DefaultHealthCheckURL
	}
	result := HealthCheckResult{
		Address:   address,
		TargetURL: targetURL,
	}
	normalized, ok := NormalizeProxyAddress(address)
	if !ok {
		result.Duration = time.Since(started)
		result.Error = ErrProxyUnavailable.Error()
		return result
	}
	proxyURL, err := url.Parse(normalized)
	if err != nil {
		result.Duration = time.Since(started)
		result.Error = err.Error()
		return result
	}
	timeout := options.Timeout
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	transport := &http.Transport{Proxy: http.ProxyURL(proxyURL)}
	client := options.HTTPClient
	if client == nil {
		client = &http.Client{Transport: transport, Timeout: timeout}
	} else if client.Transport == nil {
		cloned := *client
		cloned.Transport = transport
		client = &cloned
	}
	reqCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	request, err := http.NewRequestWithContext(reqCtx, http.MethodGet, targetURL, nil)
	if err != nil {
		result.Duration = time.Since(started)
		result.Error = err.Error()
		return result
	}
	response, err := client.Do(request)
	if err != nil {
		result.Duration = time.Since(started)
		result.Error = err.Error()
		return result
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 1024))
	result.Duration = time.Since(started)
	result.StatusCode = response.StatusCode
	result.OK = response.StatusCode >= 200 && response.StatusCode < 400
	if !result.OK {
		result.Error = fmt.Sprintf("HTTP %d", response.StatusCode)
	}
	return result
}
