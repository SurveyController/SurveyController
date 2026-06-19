package credamo

import (
	"fmt"
	"net/url"
	"regexp"
	"strings"
)

const defaultOrigin = "https://www.credamo.com"

var shortCodeRE = regexp.MustCompile(`^[A-Za-z0-9_]+(?:ano)?$`)

func originFromURL(rawURL string) string {
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return defaultOrigin
	}
	return parsed.Scheme + "://" + parsed.Host
}

func shortURLFromURL(rawURL string) (string, error) {
	text := strings.TrimSpace(rawURL)
	parsed, _ := url.Parse(text)
	candidates := []string{parsed.Path, parsed.Fragment, text}
	for _, candidate := range candidates {
		clean := strings.Trim(strings.Split(strings.TrimSpace(strings.TrimPrefix(candidate, "#")), "?")[0], "/")
		if clean == "" {
			continue
		}
		parts := splitNonEmpty(clean, "/")
		for i, part := range parts {
			if part == "s" && i+1 < len(parts) {
				return strings.TrimSpace(parts[i+1]), nil
			}
		}
		if shortCodeRE.MatchString(clean) {
			return clean, nil
		}
	}
	return "", fmt.Errorf("见数链接缺少短链接编号")
}

func noAuthShortURL(shortURL string) (string, error) {
	short := strings.TrimRight(strings.TrimSpace(shortURL), "/")
	switch {
	case strings.HasSuffix(short, "_"):
		return strings.TrimSuffix(short, "_") + "ano", nil
	case strings.HasSuffix(short, "ano"):
		return short, nil
	default:
		return "", fmt.Errorf("见数 HTTP 目前只支持免登录短链接")
	}
}

func answerPageURL(origin string, shortURL string) string {
	return strings.TrimRight(origin, "/") + "/answer.html#/s/" + shortURL
}

func splitNonEmpty(value string, sep string) []string {
	parts := strings.Split(value, sep)
	result := make([]string, 0, len(parts))
	for _, part := range parts {
		if strings.TrimSpace(part) != "" {
			result = append(result, strings.TrimSpace(part))
		}
	}
	return result
}
