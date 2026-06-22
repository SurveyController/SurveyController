package proxycore

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const DefaultCustomProxySource = "custom"

type HTTPFetcherOptions struct {
	Endpoint   string
	HTTPClient *http.Client
	Headers    map[string]string
	Source     string
	Timeout    time.Duration
}

type HTTPFetcher struct {
	endpoint   string
	httpClient *http.Client
	headers    map[string]string
	source     string
	timeout    time.Duration
}

func NewHTTPFetcher(options HTTPFetcherOptions) (*HTTPFetcher, error) {
	endpoint := strings.TrimSpace(options.Endpoint)
	if endpoint == "" {
		return nil, fmt.Errorf("%w: 自定义代理 API 为空", ErrProxyUnavailable)
	}
	httpClient := options.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 10 * time.Second}
	}
	source := strings.TrimSpace(options.Source)
	if source == "" {
		source = DefaultCustomProxySource
	}
	timeout := options.Timeout
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	return &HTTPFetcher{
		endpoint:   endpoint,
		httpClient: httpClient,
		headers:    cloneStringMap(options.Headers),
		source:     source,
		timeout:    timeout,
	}, nil
}

func (f *HTTPFetcher) Fetch(ctx context.Context, _ int) ([]ProxyLease, error) {
	if f == nil || strings.TrimSpace(f.endpoint) == "" {
		return nil, ErrProxyUnavailable
	}
	reqCtx, cancel := context.WithTimeout(ctx, f.timeout)
	defer cancel()
	request, err := http.NewRequestWithContext(reqCtx, http.MethodGet, f.endpoint, nil)
	if err != nil {
		return nil, err
	}
	for key, value := range f.headers {
		request.Header.Set(key, value)
	}
	response, err := f.httpClient.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, 4<<20))
	if err != nil {
		return nil, err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, fmt.Errorf("%w: 自定义代理 API 返回 HTTP %d", ErrProxyUnavailable, response.StatusCode)
	}
	return ParseProxyLeases(body, f.source)
}

func cloneStringMap(src map[string]string) map[string]string {
	if len(src) == 0 {
		return nil
	}
	dst := make(map[string]string, len(src))
	for key, value := range src {
		key = strings.TrimSpace(key)
		if key == "" {
			continue
		}
		dst[key] = value
	}
	return dst
}
