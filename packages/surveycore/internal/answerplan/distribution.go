package answerplan

import (
	"math"
	"math/rand"
	"strconv"
	"strings"

	"surveycontroller/surveycore/internal/model"
)

const (
	personaBoostFactor    = 3.0
	standardWarmupSamples = 12
	standardGain          = 4.2
	standardMinFactor     = 0.45
	standardMaxFactor     = 2.2
	standardGapLimit      = 0.42
)

func selectionEntry(question model.QuestionMeta, entry model.QuestionEntry, rowIndex *int, count int, options BuildOptions) (model.QuestionEntry, bool) {
	values := effectiveProbabilityValues(entry, rowIndex, count)
	strictRatio := isStrictRatioEntry(entry)
	hasDimension := activeDimension(entry)
	if !strictRatio {
		values = applyPersonaBoost(question.OptionTexts, values, options.Persona)
	}
	if hasDimension && options.DimensionBases != nil {
		values = applyDimensionTendency(values, count, entry.Dimension, options.DimensionBases, options.Persona)
	}
	trackDistribution := false
	if options.Runtime != nil && (strictRatio || hasDimension) {
		reference := append([]float64(nil), values...)
		values = resolveDistributionProbabilities(values, count, options.Runtime, question.Num, rowIndex)
		if strictRatio {
			values = enforceReferenceRankOrder(values, reference)
		}
		trackDistribution = true
	}
	cloned := entry
	cloned.Probabilities = values
	return cloned, trackDistribution
}

func multipleSelectionEntry(question model.QuestionMeta, entry model.QuestionEntry, options BuildOptions) model.QuestionEntry {
	if isStrictRatioEntry(entry) {
		return entry
	}
	values := fitProbabilityCount(ProbabilityValues(entry.Probabilities), maxInt(1, question.Options))
	values = applyPersonaBoost(question.OptionTexts, values, options.Persona)
	cloned := entry
	cloned.Probabilities = values
	return cloned
}

func effectiveProbabilityValues(entry model.QuestionEntry, rowIndex *int, count int) []float64 {
	var values []float64
	if rowIndex != nil {
		values = ProbabilityRowValues(entry.Probabilities, *rowIndex)
		if positiveTotal(values) <= 0 {
			values = ProbabilityRowValues(entry.CustomWeights, *rowIndex)
		}
	}
	if positiveTotal(values) <= 0 {
		values = ProbabilityValues(entry.Probabilities)
	}
	if positiveTotal(values) <= 0 {
		values = ProbabilityValues(entry.CustomWeights)
	}
	return fitProbabilityCount(values, count)
}

func isStrictRatioEntry(entry model.QuestionEntry) bool {
	mode := strings.ToLower(strings.TrimSpace(entry.DistributionMode))
	if mode != "custom" {
		return false
	}
	return hasPositiveWeightValues(entry.CustomWeights) || hasPositiveWeightValues(entry.Probabilities)
}

func activeDimension(entry model.QuestionEntry) bool {
	dimension := strings.TrimSpace(entry.Dimension)
	return dimension != "" && dimension != "未分组"
}

func applyDimensionTendency(values []float64, count int, dimension string, bases map[string]float64, persona *model.Persona) []float64 {
	if count <= 0 {
		return nil
	}
	key := strings.TrimSpace(dimension)
	if key == "" || key == "未分组" {
		return values
	}
	baseRatio, ok := bases[key]
	if !ok {
		baseRatio = generateBaseRatio(count, values, persona)
		bases[key] = baseRatio
	}
	base := int(math.Round(clampFloat(baseRatio, 0, 1) * float64(maxInt(1, count-1))))
	base = minInt(maxInt(base, 0), count-1)
	window := tendencyWindow(count)
	if window <= 0 {
		return oneHotWeights(count, base)
	}
	low := maxInt(0, base-window)
	high := minInt(count-1, base+window)
	adjusted := fitProbabilityCount(values, count)
	if positiveTotal(adjusted) <= 0 {
		for index := range adjusted {
			adjusted[index] = 1
		}
	}
	for index := range adjusted {
		distance := absInt(index - base)
		if index < low || index > high {
			adjusted[index] *= 0.25
			continue
		}
		adjusted[index] *= tendencyDecay(distance, window)
	}
	if positiveTotal(adjusted) <= 0 {
		return oneHotWeights(count, base)
	}
	return adjusted
}

func generateBaseRatio(count int, values []float64, persona *model.Persona) float64 {
	if positiveTotal(values) <= 0 {
		if persona != nil && persona.SatisfactionTendency > 0 {
			return clampFloat(persona.SatisfactionTendency+rand.NormFloat64()*0.1, 0, 1)
		}
		return rand.Float64()
	}
	index := SelectedIndex(model.QuestionEntry{Probabilities: values}, count)
	return float64(index) / float64(maxInt(1, count-1))
}

func tendencyWindow(count int) int {
	if count <= 3 {
		return 0
	}
	window := int(math.Round(float64(count) * 0.28))
	if window < 1 {
		window = 1
	}
	if window > 2 {
		window = 2
	}
	return window
}

func tendencyDecay(distance int, window int) float64 {
	if distance <= 0 {
		return 1.0
	}
	if window <= 0 {
		return 0
	}
	normalized := math.Min(1, float64(distance)/float64(window))
	return math.Max(0.55, 1.0-(0.45*normalized))
}

func oneHotWeights(count int, index int) []float64 {
	result := make([]float64, maxInt(1, count))
	result[minInt(maxInt(index, 0), len(result)-1)] = 1
	return result
}

func absInt(value int) int {
	if value < 0 {
		return -value
	}
	return value
}

func applyPersonaBoost(optionTexts []string, weights []float64, persona *model.Persona) []float64 {
	boosted := append([]float64(nil), weights...)
	if persona == nil || len(boosted) == 0 {
		return boosted
	}
	keywords := personaKeywords(persona)
	if len(keywords) == 0 {
		return boosted
	}
	for index, text := range optionTexts {
		if index >= len(boosted) || strings.TrimSpace(text) == "" {
			continue
		}
		for _, keyword := range keywords {
			if keyword != "" && strings.Contains(text, keyword) {
				boosted[index] *= personaBoostFactor
				break
			}
		}
	}
	return boosted
}

func personaKeywords(persona *model.Persona) []string {
	if persona == nil {
		return nil
	}
	mapping := persona.KeywordMap()
	keywords := make([]string, 0)
	for _, values := range mapping {
		for _, value := range values {
			if text := strings.TrimSpace(value); text != "" {
				keywords = append(keywords, text)
			}
		}
	}
	return keywords
}

func resolveDistributionProbabilities(values []float64, optionCount int, runtime model.AnswerRuntime, questionNum int, rowIndex *int) []float64 {
	target := normalizeDistributionTarget(values, optionCount)
	if runtime == nil || questionNum <= 0 || optionCount <= 0 || len(target) == 0 {
		return target
	}
	total, counts := runtime.SnapshotDistributionStats(distributionStatKey(questionNum, rowIndex), optionCount)
	if total <= 0 {
		return target
	}
	sampleFactor := math.Min(1.0, float64(total)/float64(standardWarmupSamples))
	if sampleFactor <= 0 {
		return target
	}
	adjusted := make([]float64, len(target))
	for index, targetRatio := range target {
		if targetRatio <= 0 {
			continue
		}
		actualRatio := 0.0
		if index < len(counts) {
			actualRatio = float64(counts[index]) / float64(total)
		}
		gap := math.Max(-standardGapLimit, math.Min(standardGapLimit, targetRatio-actualRatio))
		factor := math.Exp(standardGain * sampleFactor * gap)
		factor = math.Max(standardMinFactor, math.Min(standardMaxFactor, factor))
		adjusted[index] = targetRatio * factor
	}
	return normalizeDistributionTarget(adjusted, optionCount)
}

func normalizeDistributionTarget(values []float64, optionCount int) []float64 {
	count := maxInt(0, optionCount)
	if count == 0 {
		return nil
	}
	fitted := fitProbabilityCount(values, count)
	total := positiveTotal(fitted)
	if total <= 0 {
		result := make([]float64, count)
		for index := range result {
			result[index] = 1 / float64(count)
		}
		return result
	}
	for index := range fitted {
		if fitted[index] <= 0 || math.IsNaN(fitted[index]) || math.IsInf(fitted[index], 0) {
			fitted[index] = 0
			continue
		}
		fitted[index] /= total
	}
	return fitted
}

func enforceReferenceRankOrder(values []float64, reference []float64) []float64 {
	adjusted := append([]float64(nil), values...)
	groups := rankGroups(reference)
	if len(groups) <= 1 {
		return adjusted
	}
	var previousFloor *float64
	for _, group := range groups {
		groupValues := make([]float64, 0, len(group))
		for _, index := range group {
			if index >= 0 && index < len(adjusted) {
				groupValues = append(groupValues, adjusted[index])
			}
		}
		if len(groupValues) == 0 {
			continue
		}
		if previousFloor != nil {
			for _, index := range group {
				if index >= 0 && index < len(adjusted) {
					adjusted[index] = math.Min(adjusted[index], *previousFloor)
				}
			}
			groupValues = groupValues[:0]
			for _, index := range group {
				if index >= 0 && index < len(adjusted) {
					groupValues = append(groupValues, adjusted[index])
				}
			}
		}
		currentMin := minPositiveOrZero(groupValues)
		if previousFloor == nil || currentMin < *previousFloor {
			value := currentMin
			previousFloor = &value
		}
	}
	return normalizeDistributionTarget(adjusted, len(adjusted))
}

func rankGroups(values []float64) [][]int {
	weights := make([]float64, 0)
	groupsByWeight := map[float64][]int{}
	for index, raw := range values {
		if raw <= 0 || math.IsNaN(raw) || math.IsInf(raw, 0) {
			continue
		}
		if _, ok := groupsByWeight[raw]; !ok {
			weights = append(weights, raw)
		}
		groupsByWeight[raw] = append(groupsByWeight[raw], index)
	}
	for i := 0; i < len(weights); i++ {
		for j := i + 1; j < len(weights); j++ {
			if weights[j] > weights[i] {
				weights[i], weights[j] = weights[j], weights[i]
			}
		}
	}
	result := make([][]int, 0, len(weights))
	for _, weight := range weights {
		result = append(result, groupsByWeight[weight])
	}
	return result
}

func minPositiveOrZero(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	minValue := values[0]
	for _, value := range values[1:] {
		if value < minValue {
			minValue = value
		}
	}
	if minValue < 0 || math.IsNaN(minValue) || math.IsInf(minValue, 0) {
		return 0
	}
	return minValue
}

func recordPendingDistribution(options BuildOptions, questionNum int, rowIndex *int, optionIndex int, optionCount int) {
	if options.Runtime == nil || questionNum <= 0 {
		return
	}
	options.Runtime.AppendPendingDistributionChoice(
		options.RuntimeOwner,
		distributionStatKey(questionNum, rowIndex),
		optionIndex,
		optionCount,
	)
}

func distributionStatKey(questionNum int, rowIndex *int) string {
	if rowIndex == nil {
		return "q:" + strconv.Itoa(questionNum)
	}
	return "matrix:" + strconv.Itoa(questionNum) + ":" + strconv.Itoa(*rowIndex)
}

func hasPositiveWeightValues(raw any) bool {
	switch raw.(type) {
	case int, int64, float64, string:
		value := floatValue(raw)
		return value > 0 && !math.IsNaN(value) && !math.IsInf(value, 0)
	}
	values := ProbabilityValues(raw)
	if positiveTotal(values) > 0 {
		return true
	}
	switch nested := raw.(type) {
	case [][]float64:
		for _, row := range nested {
			if positiveTotal(row) > 0 {
				return true
			}
		}
	case [][]int:
		for _, row := range nested {
			if positiveTotal(ProbabilityValues(row)) > 0 {
				return true
			}
		}
	case []any:
		for _, item := range nested {
			if hasPositiveWeightValues(item) {
				return true
			}
		}
	}
	return false
}
