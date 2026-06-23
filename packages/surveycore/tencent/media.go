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

func questionMedia(question map[string]any, providerType string) []map[string]any {
	media := make([]map[string]any, 0)
	seen := map[string]bool{}
	add := func(scope string, index any, label string, urls []string) {
		for _, rawURL := range urls {
			url := normalizeMediaURL(rawURL)
			if url == "" {
				continue
			}
			key := scope + "|" + stringValue(index) + "|" + url
			if seen[key] {
				continue
			}
			seen[key] = true
			media = append(media, map[string]any{
				"kind":       "image",
				"scope":      scope,
				"index":      index,
				"source_url": url,
				"label":      label,
			})
		}
	}
	add("title", nil, "题干图", append(collectImageURLs(question["title"], 0), collectImageURLs(question["description"], 0)...))
	optionTexts := buildOptionTexts(question, providerType)
	for index, option := range asMapList(question["options"]) {
		label := "选项 " + stringValue(index+1)
		if index < len(optionTexts) && optionTexts[index] != "" {
			label = optionTexts[index]
		}
		add("option", index, label, collectImageURLs(option, 0))
	}
	rowTexts := buildRowTexts(question)
	for index, row := range asMapList(question["sub_titles"]) {
		label := "第 " + stringValue(index+1) + " 行"
		if index < len(rowTexts) && rowTexts[index] != "" {
			label = rowTexts[index]
		}
		add("row", index, label, collectImageURLs(row, 0))
	}
	return media
}
