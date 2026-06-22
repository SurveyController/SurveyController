package wjx

import (
	"fmt"
	"net/url"
	"strings"
)

func shortIDFromURL(rawURL string) (string, error) {
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil {
		return "", ParseError{Message: "问卷星链接格式无效"}
	}
	path := strings.Trim(parsed.Path, "/")
	if path == "" {
		return "", ParseError{Message: "问卷星链接缺少 shortid"}
	}
	parts := strings.Split(path, "/")
	last := strings.TrimSpace(parts[len(parts)-1])
	last = strings.TrimSuffix(last, ".aspx")
	if last == "" {
		return "", ParseError{Message: "问卷星链接缺少 shortid"}
	}
	return last, nil
}

func submitDomain(rawURL string) string {
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	if err == nil && strings.Contains(strings.ToLower(parsed.Host), "ks.wjx.com") {
		return "ks.wjx.com"
	}
	return "v.wjx.cn"
}

func submitEndpoint(rawURL string) string {
	return fmt.Sprintf("https://%s/joinnew/processjq.ashx", submitDomain(rawURL))
}
