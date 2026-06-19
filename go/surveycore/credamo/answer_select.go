package credamo

import "surveycontroller/surveycore/internal/model"

func selectedIndex(entry model.QuestionEntry, count int) int {
	if count <= 0 {
		return 0
	}
	if values, ok := entry.Probabilities.([]float64); ok {
		for index, value := range values {
			if index < count && value > 0 {
				return index
			}
		}
	}
	if values, ok := entry.Probabilities.([]any); ok {
		for index, value := range values {
			if index < count && floatValue(value) > 0 {
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
	if values, ok := entry.Probabilities.([]float64); ok {
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
