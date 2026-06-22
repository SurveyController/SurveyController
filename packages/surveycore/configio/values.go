package configio

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

func defaultString(raw any, fallback string) string {
	text := strings.TrimSpace(stringValue(raw))
	if text == "" {
		return fallback
	}
	return text
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

func intValue(raw any, fallback int) int {
	switch typed := raw.(type) {
	case int:
		return typed
	case int64:
		return int(typed)
	case float64:
		return int(typed)
	case string:
		value, err := strconv.Atoi(strings.TrimSpace(typed))
		if err == nil {
			return value
		}
	}
	return fallback
}

func positiveInt(raw any, fallback int) int {
	value := intValue(raw, fallback)
	if value < 1 {
		return fallback
	}
	return value
}

func floatValue(raw any, fallback float64) float64 {
	switch typed := raw.(type) {
	case int:
		return float64(typed)
	case int64:
		return float64(typed)
	case float64:
		return typed
	case string:
		value, err := strconv.ParseFloat(strings.TrimSpace(typed), 64)
		if err == nil {
			return value
		}
	}
	return fallback
}

func boolValue(raw any, fallback bool) bool {
	switch typed := raw.(type) {
	case bool:
		return typed
	case int:
		return typed != 0
	case float64:
		return typed != 0
	case string:
		switch strings.ToLower(strings.TrimSpace(typed)) {
		case "1", "true", "yes", "on":
			return true
		case "0", "false", "no", "off", "":
			return false
		}
	}
	return fallback
}

func intPair(raw any, fallback [2]int) [2]int {
	items, ok := raw.([]any)
	if !ok || len(items) < 2 {
		return fallback
	}
	left := intValue(items[0], fallback[0])
	right := intValue(items[1], fallback[1])
	if left < 0 {
		left = 0
	}
	if right < left {
		right = left
	}
	return [2]int{left, right}
}

func stringPair(raw any) [2]string {
	items, ok := raw.([]any)
	if !ok || len(items) < 2 {
		return [2]string{}
	}
	return [2]string{strings.TrimSpace(stringValue(items[0])), strings.TrimSpace(stringValue(items[1]))}
}

func minInt(left int, right int) int {
	if left < right {
		return left
	}
	return right
}
