package credamo

import (
	"encoding/json"
	"math/rand"

	"surveycontroller/surveycore/internal/model"
)

func selectedIndex(entry model.QuestionEntry, count int) int {
	if count <= 0 {
		return 0
	}
	values := probabilityValues(entry.Probabilities)
	if len(values) > 0 {
		total := 0.0
		for index, value := range values {
			if index < count && value > 0 {
				total += value
			}
		}
		if total > 0 {
			pick := rand.Float64() * total
			acc := 0.0
			for index, value := range values {
				if index >= count || value <= 0 {
					continue
				}
				acc += value
				if pick <= acc {
					return index
				}
			}
		}
		for index, value := range values {
			if index < count && value > 0 {
				return index
			}
		}
	}
	return 0
}

func selectedIndices(entry model.QuestionEntry, count int, allowMultiple bool) []int {
	if count <= 0 {
		return nil
	}
	if !allowMultiple {
		return []int{selectedIndex(entry, count)}
	}
	selected := []int{}
	values := probabilityValues(entry.Probabilities)
	if len(values) > 0 {
		for index, value := range values {
			if index < count && value > 0 {
				selected = append(selected, index)
			}
		}
	}
	if len(selected) == 0 {
		selected = append(selected, 0)
	}
	return selected
}

func probabilityValues(raw any) []float64 {
	switch values := raw.(type) {
	case []float64:
		return append([]float64(nil), values...)
	case []int:
		result := make([]float64, 0, len(values))
		for _, value := range values {
			result = append(result, float64(value))
		}
		return result
	case []any:
		result := make([]float64, 0, len(values))
		for _, value := range values {
			result = append(result, floatValue(value))
		}
		return result
	case []json.Number:
		result := make([]float64, 0, len(values))
		for _, value := range values {
			number, _ := value.Float64()
			result = append(result, number)
		}
		return result
	default:
		return nil
	}
}

func choicePayload(raw map[string]any, fillText string) map[string]any {
	return map[string]any{
		"choiceId":      idFromMapping(raw, "choiceId", "id"),
		"choiceContent": fillText,
	}
}

func idFromMapping(item map[string]any, keys ...string) any {
	for _, key := range keys {
		value := item[key]
		if value != nil && stringValue(value) != "" {
			return normalizeID(value)
		}
	}
	return ""
}

func normalizeID(value any) any {
	text := stringValue(value)
	if text == "" {
		return ""
	}
	if number, ok := parseInt(text); ok {
		return number
	}
	return text
}

func fillTextAt(values []*string, index int) string {
	if index < 0 || index >= len(values) || values[index] == nil {
		return ""
	}
	return *values[index]
}
