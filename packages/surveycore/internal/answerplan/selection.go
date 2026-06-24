package answerplan

import (
	"math/rand"

	"surveycontroller/surveycore/internal/model"
)

func SelectedIndex(entry model.QuestionEntry, count int) int {
	if count <= 0 {
		return 0
	}
	values := ProbabilityValues(entry.Probabilities)
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
	return 0
}

func SelectedMatrixIndex(entry model.QuestionEntry, row int, count int) int {
	rowValues := ProbabilityRowValues(entry.Probabilities, row)
	if len(rowValues) == 0 {
		return SelectedIndex(entry, count)
	}
	rowEntry := entry
	rowEntry.Probabilities = rowValues
	return SelectedIndex(rowEntry, count)
}

func SelectedIndices(entry model.QuestionEntry, count int, minRequired int, maxAllowed int) []int {
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
	values := fitProbabilityCount(ProbabilityValues(entry.Probabilities), count)
	if positiveTotal(values) <= 0 {
		return randomMultipleSelection(count, minRequired, maxAllowed)
	}
	selected := make([]int, 0)
	for index, value := range values {
		probability := clampFloat(value, 0, 100)
		if index < count && probability > 0 && rand.Float64()*100 <= probability {
			selected = append(selected, index)
		}
	}
	if len(selected) == 0 {
		positive := positiveIndices(values, count)
		if len(positive) > 0 {
			selected = append(selected, positive[rand.Intn(len(positive))])
		}
	}
	if len(selected) > maxAllowed {
		selected = sampleIntSubset(selected, maxAllowed)
	}
	positive := shuffledInts(positiveIndices(values, count))
	for index := 0; index < count && len(selected) < minRequired; index++ {
		if index < len(positive) && !containsIndex(selected, positive[index]) {
			selected = append(selected, positive[index])
		}
	}
	any := shuffledRange(count)
	for index := 0; index < len(any) && len(selected) < minRequired; index++ {
		if !containsIndex(selected, any[index]) {
			selected = append(selected, any[index])
		}
	}
	selected = uniqueInts(selected)
	if len(selected) > maxAllowed {
		selected = selected[:maxAllowed]
	}
	return selected
}

func SelectedTextIndex(candidates []string, raw any) int {
	if len(candidates) <= 1 {
		return 0
	}
	values := ProbabilityValues(raw)
	if len(values) != len(candidates) || positiveTotal(values) <= 0 {
		values = make([]float64, len(candidates))
		for index := range values {
			values[index] = 1
		}
	}
	entry := model.QuestionEntry{Probabilities: values}
	return SelectedIndex(entry, len(candidates))
}

func containsIndex(values []int, target int) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func uniqueInts(values []int) []int {
	seen := map[int]bool{}
	result := make([]int, 0, len(values))
	for _, value := range values {
		if value < 0 || seen[value] {
			continue
		}
		seen[value] = true
		result = append(result, value)
	}
	return result
}

func positiveIndices(values []float64, count int) []int {
	result := make([]int, 0, count)
	for index := 0; index < count; index++ {
		if index < len(values) && values[index] > 0 {
			result = append(result, index)
		}
	}
	return result
}

func randomMultipleSelection(count int, minRequired int, maxAllowed int) []int {
	if count <= 0 {
		return nil
	}
	if maxAllowed <= 0 || maxAllowed > count {
		maxAllowed = count
	}
	if minRequired <= 0 {
		minRequired = 1
	}
	if minRequired > maxAllowed {
		minRequired = maxAllowed
	}
	target := minRequired
	if maxAllowed > minRequired {
		target += rand.Intn(maxAllowed - minRequired + 1)
	}
	return sampleIntSubset(shuffledRange(count), target)
}

func shuffledRange(count int) []int {
	values := make([]int, 0, count)
	for index := 0; index < count; index++ {
		values = append(values, index)
	}
	return shuffledInts(values)
}

func shuffledInts(values []int) []int {
	result := append([]int(nil), values...)
	for index := len(result) - 1; index > 0; index-- {
		swap := rand.Intn(index + 1)
		result[index], result[swap] = result[swap], result[index]
	}
	return result
}

func sampleIntSubset(values []int, size int) []int {
	if size <= 0 {
		return nil
	}
	unique := uniqueInts(values)
	if len(unique) <= size {
		return unique
	}
	return shuffledInts(unique)[:size]
}
