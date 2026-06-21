package tencent

import (
	"fmt"
	"html"
	"math"
	"regexp"
	"strconv"
	"strings"
)

var (
	htmlTagRE         = regexp.MustCompile(`<[^>]+>`)
	spaceRE           = regexp.MustCompile(`\s+`)
	fillBlankTokenRE  = regexp.MustCompile(`(?i)\{fillblank-[^{}]+\}`)
	fillBlankSuffixRE = regexp.MustCompile(`(?i)\s*[_＿]*\s*\{fillblank-[^{}]+\}`)
)

func firstAny(values ...any) any {
	for _, value := range values {
		if value == nil {
			continue
		}
		if text, ok := value.(string); ok && strings.TrimSpace(text) == "" {
			continue
		}
		return value
	}
	return nil
}

func firstString(values ...any) string {
	for _, value := range values {
		text := normalizeText(value)
		if text != "" {
			return text
		}
	}
	return ""
}

func stringValue(value any) string {
	switch typed := value.(type) {
	case nil:
		return ""
	case string:
		return typed
	case fmt.Stringer:
		return typed.String()
	case float64:
		if math.Trunc(typed) == typed {
			return strconv.FormatInt(int64(typed), 10)
		}
		return strconv.FormatFloat(typed, 'f', -1, 64)
	case float32:
		return strconv.FormatFloat(float64(typed), 'f', -1, 32)
	case int:
		return strconv.Itoa(typed)
	case int64:
		return strconv.FormatInt(typed, 10)
	case bool:
		return strconv.FormatBool(typed)
	default:
		return fmt.Sprint(typed)
	}
}

func intValue(value any) int {
	switch typed := value.(type) {
	case int:
		return typed
	case int64:
		return int(typed)
	case float64:
		return int(typed)
	case float32:
		return int(typed)
	case string:
		number, err := strconv.Atoi(strings.TrimSpace(typed))
		if err == nil {
			return number
		}
	}
	return 0
}

func boolValue(value any) bool {
	switch typed := value.(type) {
	case bool:
		return typed
	case string:
		text := strings.TrimSpace(strings.ToLower(typed))
		return text == "true" || text == "1" || text == "yes"
	case int:
		return typed != 0
	case float64:
		return typed != 0
	default:
		return false
	}
}

func normalizeText(value any) string {
	text := strings.TrimSpace(stringValue(value))
	if text == "" {
		return ""
	}
	text = html.UnescapeString(text)
	text = stripMarkdownImages(text)
	text = htmlTagRE.ReplaceAllString(text, " ")
	return strings.TrimSpace(spaceRE.ReplaceAllString(text, " "))
}

func cleanOptionText(value any) string {
	text := normalizeText(value)
	text = fillBlankSuffixRE.ReplaceAllString(text, "")
	text = fillBlankTokenRE.ReplaceAllString(text, "")
	return normalizeText(text)
}

func asMapList(value any) []map[string]any {
	raw, ok := value.([]any)
	if !ok {
		return nil
	}
	result := make([]map[string]any, 0, len(raw))
	for _, item := range raw {
		if mapped, ok := item.(map[string]any); ok {
			result = append(result, mapped)
		}
	}
	return result
}

func cleanTextList(values []string) []string {
	result := make([]string, 0, len(values))
	for _, value := range values {
		text := normalizeText(value)
		if text != "" {
			result = append(result, text)
		}
	}
	return result
}

func maxInt(left int, right int) int {
	if left > right {
		return left
	}
	return right
}
