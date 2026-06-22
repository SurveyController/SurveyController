package tencent

import (
	"regexp"
	"strings"
)

var markdownImageRE = regexp.MustCompile(`!\[[^\]]*]\(([^)\s]+)\)(?:\{[^}]*\})?`)

func markdownImageURLs(text any) []string {
	rawText := strings.TrimSpace(stringValue(text))
	if rawText == "" {
		return nil
	}
	matches := markdownImageRE.FindAllStringSubmatch(rawText, -1)
	result := make([]string, 0, len(matches))
	for _, match := range matches {
		if len(match) > 1 && strings.TrimSpace(match[1]) != "" {
			result = append(result, strings.TrimSpace(match[1]))
		}
	}
	return result
}

func stripMarkdownImages(text string) string {
	return markdownImageRE.ReplaceAllString(text, " ")
}

func normalizeMediaURL(raw any) string {
	text := strings.TrimSpace(stringValue(raw))
	if text == "" {
		return ""
	}
	if urls := markdownImageURLs(text); len(urls) > 0 {
		text = urls[0]
	}
	if strings.HasPrefix(text, "//") {
		return "https:" + text
	}
	return text
}

func collectImageURLs(value any, depth int) []string {
	if depth > 5 || value == nil {
		return nil
	}
	switch typed := value.(type) {
	case map[string]any:
		var collected []string
		for key, item := range typed {
			keyText := strings.ToLower(strings.TrimSpace(key))
			switch keyText {
			case "img", "image", "image_url", "img_url", "pic", "pic_url", "url", "src":
				if normalized := normalizeMediaURL(item); normalized != "" {
					collected = append(collected, normalized)
				}
			}
			collected = append(collected, collectImageURLs(item, depth+1)...)
		}
		return collected
	case []any:
		var collected []string
		for _, item := range typed {
			collected = append(collected, collectImageURLs(item, depth+1)...)
		}
		return collected
	default:
		normalized := normalizeMediaURL(value)
		lowered := strings.ToLower(normalized)
		if normalized != "" && (strings.Contains(lowered, ".png") || strings.Contains(lowered, ".jpg") || strings.Contains(lowered, ".jpeg") || strings.Contains(lowered, ".webp") || strings.Contains(lowered, ".gif") || strings.Contains(lowered, ".bmp")) {
			return []string{normalized}
		}
		return nil
	}
}
