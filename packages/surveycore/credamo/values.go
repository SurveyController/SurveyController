package credamo

import (
	"fmt"
	"math"
	"strconv"
	"strings"
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

func int64Value(value any) int64 {
	switch typed := value.(type) {
	case int:
		return int64(typed)
	case int64:
		return typed
	case float64:
		return int64(typed)
	case float32:
		return int64(typed)
	case string:
		number, err := strconv.ParseInt(strings.TrimSpace(typed), 10, 64)
		if err == nil {
			return number
		}
	}
	return 0
}

func floatValue(value any) float64 {
	switch typed := value.(type) {
	case int:
		return float64(typed)
	case int64:
		return float64(typed)
	case float64:
		return typed
	case float32:
		return float64(typed)
	case string:
		number, err := strconv.ParseFloat(strings.TrimSpace(typed), 64)
		if err == nil {
			return number
		}
	}
	return 0
}

func parseInt(value string) (int, bool) {
	number, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil {
		return 0, false
	}
	return number, true
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

func stringList(value any) []string {
	raw, ok := value.([]string)
	if ok {
		return raw
	}
	items, ok := value.([]any)
	if !ok {
		return nil
	}
	result := make([]string, 0, len(items))
	for _, item := range items {
		result = append(result, stringValue(item))
	}
	return result
}

func intList(value any) []int {
	items, ok := value.([]any)
	if !ok {
		return nil
	}
	result := make([]int, 0, len(items))
	for _, item := range items {
		number := intValue(item)
		if number >= 0 {
			result = append(result, number)
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

func itemTexts(items []map[string]any, keys ...string) []string {
	result := make([]string, 0, len(items))
	for _, item := range items {
		for _, key := range keys {
			if text := normalizeText(item[key]); text != "" {
				result = append(result, text)
				break
			}
		}
	}
	return result
}

func containsString(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func maxInt(left int, right int) int {
	if left > right {
		return left
	}
	return right
}
