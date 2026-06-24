package answerplan

import (
	"encoding/json"
	"fmt"
	"math"
	"strconv"
	"strings"

	"surveycontroller/surveycore/internal/model"
)

func FillTextAt(values []*string, index int) string {
	if index < 0 || index >= len(values) || values[index] == nil {
		return ""
	}
	return strings.TrimSpace(*values[index])
}

func OptionFillText(entry model.QuestionEntry, question model.QuestionMeta, index int) string {
	text := FillTextAt(entry.OptionFillTexts, index)
	if text == "__AI_FILL__" {
		return defaultFillText
	}
	if text != "" {
		return resolveDynamicTextToken(text)
	}
	if optionRequiresFill(entry, question, index) {
		return defaultFillText
	}
	return ""
}

func optionRequiresFill(entry model.QuestionEntry, question model.QuestionMeta, index int) bool {
	if index < 0 {
		return false
	}
	for _, value := range entry.FillableOptionIndices {
		if value == index {
			return true
		}
	}
	for _, value := range question.FillableOptions {
		if value == index {
			return true
		}
	}
	return false
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if text := strings.TrimSpace(value); text != "" {
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
	case int:
		return strconv.Itoa(typed)
	default:
		return fmt.Sprint(typed)
	}
}

func floatValue(value any) float64 {
	switch typed := value.(type) {
	case int:
		return float64(typed)
	case int64:
		return float64(typed)
	case float64:
		return typed
	case json.Number:
		number, _ := typed.Float64()
		return number
	case string:
		number, _ := strconv.ParseFloat(strings.TrimSpace(typed), 64)
		return number
	default:
		return 0
	}
}

func clampFloat(value float64, minValue float64, maxValue float64) float64 {
	if math.IsNaN(value) || math.IsInf(value, 0) {
		return minValue
	}
	if value < minValue {
		return minValue
	}
	if value > maxValue {
		return maxValue
	}
	return value
}

func maxInt(left int, right int) int {
	if left > right {
		return left
	}
	return right
}

func minInt(left int, right int) int {
	if left < right {
		return left
	}
	return right
}
