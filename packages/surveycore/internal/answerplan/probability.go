package answerplan

import "encoding/json"

func ProbabilityValues(raw any) []float64 {
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

func firstProbabilityValue(raw any) any {
	values := ProbabilityValues(raw)
	if len(values) == 0 {
		return nil
	}
	return values[0]
}

func ProbabilityRowValues(raw any, row int) []float64 {
	if row < 0 {
		return nil
	}
	switch values := raw.(type) {
	case [][]float64:
		if row < len(values) {
			return append([]float64(nil), values[row]...)
		}
	case [][]int:
		if row < len(values) {
			result := make([]float64, 0, len(values[row]))
			for _, value := range values[row] {
				result = append(result, float64(value))
			}
			return result
		}
	case [][]any:
		if row < len(values) {
			return ProbabilityValues(values[row])
		}
	case []any:
		if row < len(values) {
			switch values[row].(type) {
			case []any, []float64, []int, []json.Number:
				return ProbabilityValues(values[row])
			}
		}
	}
	return nil
}
