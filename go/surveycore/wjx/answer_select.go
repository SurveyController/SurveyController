package wjx

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

func selectedIndices(entry model.QuestionEntry, count int, minRequired int, maxAllowed int) []int {
	if count <= 0 {
		return nil
	}
	if minRequired <= 0 {
		minRequired = 1
	}
	if maxAllowed <= 0 || maxAllowed > count {
		maxAllowed = count
	}
	if minRequired > maxAllowed {
		minRequired = maxAllowed
	}
	values := probabilityValues(entry.Probabilities)
	selected := make([]int, 0)
	for index, value := range values {
		if index < count && value > 0 {
			selected = append(selected, index)
		}
	}
	if len(selected) == 0 {
		selected = append(selected, 0)
	}
	if len(selected) < minRequired {
		for index := 0; index < count && len(selected) < minRequired; index++ {
			if !containsIndex(selected, index) {
				selected = append(selected, index)
			}
		}
	}
	if len(selected) > maxAllowed {
		selected = selected[:maxAllowed]
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

func containsIndex(values []int, target int) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
