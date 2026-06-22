package tencent

import (
	"fmt"
	"net/url"
	"regexp"
	"strings"
)

var qqURLRE = regexp.MustCompile(`(?i)/s\d+/(\d+)/([A-Za-z0-9_-]+)/?$`)

func extractIdentifiers(rawURL string) (string, string, error) {
	text := strings.TrimSpace(rawURL)
	match := qqURLRE.FindStringSubmatch(text)
	if len(match) < 3 {
		return "", "", ParseError{Message: "腾讯问卷链接格式无效，请确认链接完整且公开可访问"}
	}
	return strings.TrimSpace(match[1]), strings.TrimSpace(match[2]), nil
}

func pageURL(surveyID string, hashValue string) string {
	return fmt.Sprintf("https://wj.qq.com/s2/%s/%s/", surveyID, hashValue)
}

func apiEndpoint(surveyID string, endpoint string) string {
	return fmt.Sprintf("https://wj.qq.com/api/v2/respondent/surveys/%s/%s", surveyID, endpoint)
}

func isLoginRequiredURL(raw any) bool {
	text := strings.TrimSpace(stringValue(raw))
	if text == "" {
		return false
	}
	if !strings.Contains(text, "://") {
		text = "https://" + text
	}
	parsed, err := url.Parse(text)
	if err != nil {
		return false
	}
	host := strings.ToLower(strings.SplitN(parsed.Host, ":", 2)[0])
	path := strings.TrimSpace(parsed.Path)
	return (host == "open.weixin.qq.com" && strings.HasPrefix(path, "/connect/confirm")) || (host == "wj.qq.com" && strings.EqualFold(path, "/r/login.html"))
}
