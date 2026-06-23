package proxyhttp

import (
	"net/http"
	"net/url"
	"strings"
	"time"
)

func Client(base *http.Client, proxyAddress string) (*http.Client, error) {
	proxy := strings.TrimSpace(proxyAddress)
	if proxy == "" {
		if base != nil {
			return base, nil
		}
		return &http.Client{Timeout: 30 * time.Second}, nil
	}
	if !strings.Contains(proxy, "://") {
		proxy = "http://" + proxy
	}
	proxyURL, err := url.Parse(proxy)
	if err != nil {
		return nil, err
	}
	timeout := 30 * time.Second
	if base != nil && base.Timeout > 0 {
		timeout = base.Timeout
	}
	return &http.Client{
		Timeout: timeout,
		Transport: &http.Transport{
			Proxy: http.ProxyURL(proxyURL),
		},
	}, nil
}
