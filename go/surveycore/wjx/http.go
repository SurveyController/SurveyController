package wjx

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const defaultUserAgent = "Mozilla/5.0 (Linux; Android 12; SurveyController) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Mobile Safari/537.36 MicroMessenger/8.0"

func httpClientOrDefault(client *http.Client) httpDoer {
	if client != nil {
		return client
	}
	return &http.Client{Timeout: 30 * time.Second}
}

func (p Parser) getHTML(ctx context.Context, surveyURL string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, surveyURL, nil)
	if err != nil {
		return "", err
	}
	for key, value := range requestHeaders(surveyURL, p.UserAgent) {
		req.Header.Set(key, value)
	}
	resp, err := httpClientOrDefault(p.Client).Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("http %d: %s", resp.StatusCode, string(data))
	}
	return string(data), nil
}

func requestHeaders(referer string, userAgent string) map[string]string {
	ua := strings.TrimSpace(userAgent)
	if ua == "" {
		ua = defaultUserAgent
	}
	return map[string]string{
		"Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
		"Accept-Language": "zh-CN,zh;q=0.9",
		"Referer":         referer,
		"User-Agent":      ua,
	}
}

func (r Runner) postForm(ctx context.Context, endpoint string, referer string, query url.Values, form url.Values) (string, error) {
	target := endpoint
	if encoded := query.Encode(); encoded != "" {
		target += "?" + encoded
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, target, strings.NewReader(form.Encode()))
	if err != nil {
		return "", err
	}
	for key, value := range requestHeaders(referer, r.UserAgent) {
		req.Header.Set(key, value)
	}
	req.Header.Set("Accept", "text/plain, */*; q=0.01")
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
	req.Header.Set("Origin", "https://"+submitDomain(referer))
	req.Header.Set("X-Requested-With", "XMLHttpRequest")
	resp, err := httpClientOrDefault(r.Client).Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("http %d: %s", resp.StatusCode, string(data))
	}
	return string(data), nil
}
