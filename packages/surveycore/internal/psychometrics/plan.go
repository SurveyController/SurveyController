package psychometrics

import (
	"math"
	"math/rand"
	"regexp"
	"strings"

	"surveycontroller/surveycore/internal/answerplan"
	"surveycontroller/surveycore/internal/model"
)

const (
	globalReliabilityDimension = "__global_reliability__"
	defaultTargetAlpha         = 0.85
	minTargetAlpha             = 0.60
	maxTargetAlpha             = 0.95
	microJitterSigma           = 0.03
)

type Item struct {
	QuestionNum         int
	Kind                string
	RowIndex            *int
	OptionCount         int
	Bias                string
	TargetProbabilities []float64
	ScoreByChoiceIndex  []int
}

type JointPlan struct {
	AnswersBySample map[int]map[string]int
	SampleCount     int
}

func (p *JointPlan) Choice(sampleIndex int, questionNum int, rowIndex *int) (int, bool) {
	if p == nil {
		return 0, false
	}
	answers := p.AnswersBySample[sampleIndex]
	if answers == nil {
		return 0, false
	}
	choice, ok := answers[choiceKey(questionNum, rowIndex)]
	return choice, ok
}

func BuildJointPlan(cfg *model.RuntimeConfig) *JointPlan {
	if cfg == nil || !cfg.ReliabilityModeEnabled {
		return nil
	}
	sampleCount := cfg.Target
	if sampleCount <= 0 {
		sampleCount = 1
	}
	grouped := buildBlueprint(cfg)
	if len(grouped) == 0 {
		return nil
	}
	targetAlpha := normalizeTargetAlpha(cfg.PsychoTargetAlpha)
	answers := make(map[int]map[string]int, sampleCount)
	for sampleIndex := 0; sampleIndex < sampleCount; sampleIndex++ {
		answers[sampleIndex] = map[string]int{}
	}
	hasChoices := false
	for _, items := range grouped {
		if len(items) < 2 {
			continue
		}
		choices := evaluateDimension(items, sampleCount, targetAlpha)
		for key, assigned := range choices {
			for sampleIndex, choice := range assigned {
				answers[sampleIndex][key] = choice
				hasChoices = true
			}
		}
	}
	if !hasChoices {
		return nil
	}
	return &JointPlan{AnswersBySample: answers, SampleCount: sampleCount}
}

func ApplySample(entries []model.QuestionEntry, questions []model.QuestionMeta, plan *JointPlan, sampleIndex int) []model.QuestionEntry {
	if plan == nil {
		return cloneEntries(entries)
	}
	cloned := cloneEntries(entries)
	entryByNum := map[int]int{}
	for index, entry := range cloned {
		if entry.QuestionNum != nil {
			entryByNum[*entry.QuestionNum] = index
		}
	}
	for _, question := range questions {
		if question.IsDescription {
			continue
		}
		index, ok := entryByNum[question.Num]
		if !ok {
			cloned = append(cloned, answerplan.DefaultEntry(question))
			index = len(cloned) - 1
			entryByNum[question.Num] = index
		}
		entry := cloned[index]
		if applyQuestionSample(&entry, question, plan, sampleIndex) {
			cloned[index] = entry
		}
	}
	return cloned
}

func applyQuestionSample(entry *model.QuestionEntry, question model.QuestionMeta, plan *JointPlan, sampleIndex int) bool {
	kind := normalizeKind(question, *entry)
	switch kind {
	case "single", "dropdown", "scale", "score":
		choice, ok := plan.Choice(sampleIndex, question.Num, nil)
		if !ok {
			return false
		}
		entry.Probabilities = oneHot(optionCount(question, *entry, nil, 5), choice)
		return true
	case "matrix":
		rows := maxInt(1, question.Rows)
		values := make([][]float64, rows)
		changed := false
		for row := 0; row < rows; row++ {
			rowIndex := row
			choice, ok := plan.Choice(sampleIndex, question.Num, &rowIndex)
			if !ok {
				values[row] = answerplan.ProbabilityRowValues(entry.Probabilities, row)
				if len(values[row]) == 0 {
					values[row] = answerplan.ProbabilityValues(entry.Probabilities)
				}
				continue
			}
			values[row] = oneHot(optionCount(question, *entry, &row, 5), choice)
			changed = true
		}
		if changed {
			entry.Probabilities = values
		}
		return changed
	default:
		return false
	}
}

func buildBlueprint(cfg *model.RuntimeConfig) map[string][]Item {
	questions := map[int]model.QuestionMeta{}
	for _, question := range cfg.QuestionsInfo {
		questions[question.Num] = question
	}
	grouped := map[string][]Item{}
	candidates := make([]Item, 0)
	candidateDimensions := make([]string, 0)
	hasExplicitDimension := false
	for index, entry := range cfg.QuestionEntries {
		questionNum := index + 1
		if entry.QuestionNum != nil && *entry.QuestionNum > 0 {
			questionNum = *entry.QuestionNum
		}
		question := questions[questionNum]
		if question.Num == 0 {
			question.Num = questionNum
			question.Options = entry.OptionCount
			question.Rows = entry.Rows
			question.ProviderType = entry.QuestionType
		}
		items := blueprintItems(question, entry)
		if len(items) == 0 {
			continue
		}
		dimension := strings.TrimSpace(entry.Dimension)
		if dimension != "" && dimension != "未分组" {
			hasExplicitDimension = true
		}
		for _, item := range items {
			candidates = append(candidates, item)
			candidateDimensions = append(candidateDimensions, dimension)
		}
	}
	for index, item := range candidates {
		dimension := strings.TrimSpace(candidateDimensions[index])
		if !hasExplicitDimension {
			dimension = globalReliabilityDimension
		}
		if dimension == "" || dimension == "未分组" {
			continue
		}
		grouped[dimension] = append(grouped[dimension], item)
	}
	return grouped
}

func blueprintItems(question model.QuestionMeta, entry model.QuestionEntry) []Item {
	kind := normalizeKind(question, entry)
	switch kind {
	case "scale", "score", "dropdown":
		return []Item{newItem(question, entry, kind, nil, nil)}
	case "single":
		scoreMap, ok := inferOrdinalOptionMapping(question.OptionTexts)
		if !ok {
			return nil
		}
		return []Item{newItem(question, entry, kind, nil, scoreMap)}
	case "matrix":
		rows := maxInt(1, question.Rows)
		result := make([]Item, 0, rows)
		for row := 0; row < rows; row++ {
			rowIndex := row
			result = append(result, newItem(question, entry, kind, &rowIndex, nil))
		}
		return result
	default:
		return nil
	}
}

func newItem(question model.QuestionMeta, entry model.QuestionEntry, kind string, rowIndex *int, scoreMap []int) Item {
	count := optionCount(question, entry, rowIndex, 5)
	probabilities := probabilitiesForEntry(entry, rowIndex, count)
	bias := resolveBias(entry.PsychoBias, probabilities, count)
	if len(probabilities) == 0 {
		probabilities = buildBiasTargetProbabilities(count, bias)
	}
	return Item{
		QuestionNum:         question.Num,
		Kind:                kind,
		RowIndex:            cloneIntPtr(rowIndex),
		OptionCount:         count,
		Bias:                bias,
		TargetProbabilities: normalizeProbabilityList(probabilities),
		ScoreByChoiceIndex:  append([]int(nil), scoreMap...),
	}
}

func evaluateDimension(items []Item, sampleCount int, targetAlpha float64) map[string][]int {
	theta := randomVector(sampleCount)
	standardNoise := randomMatrix(len(items), sampleCount)
	microNoise := randomMatrix(len(items), sampleCount)
	reversed := reversedKeys(items)
	type candidate struct {
		sigma   float64
		alpha   float64
		choices map[string][]int
	}
	candidates := make([]candidate, 0)
	for _, sigma := range sigmaCandidates(targetAlpha, len(items)) {
		alpha, choices := evaluate(items, sampleCount, sigma, theta, reversed, standardNoise, microNoise)
		candidates = append(candidates, candidate{sigma: sigma, alpha: alpha, choices: choices})
	}
	best := candidates[0]
	for _, candidate := range candidates[1:] {
		if alphaFitLess(candidate.alpha, best.alpha, targetAlpha) {
			best = candidate
		}
	}
	return best.choices
}

func evaluate(items []Item, sampleCount int, sigma float64, theta []float64, reversed map[string]bool, standardNoise [][]float64, microNoise [][]float64) (float64, map[string][]int) {
	choicesByItem := map[string][]int{}
	responseRows := make([][]float64, sampleCount)
	for sampleIndex := range responseRows {
		responseRows[sampleIndex] = make([]float64, len(items))
	}
	for itemIndex, item := range items {
		key := item.choiceKey()
		quotas := integerQuotas(item.TargetProbabilities, sampleCount)
		sign := 1.0
		if reversed[key] {
			sign = -1.0
		}
		scores := make([]float64, sampleCount)
		for sampleIndex := 0; sampleIndex < sampleCount; sampleIndex++ {
			scores[sampleIndex] = sign*theta[sampleIndex] + sigma*standardNoise[itemIndex][sampleIndex] + microJitterSigma*microNoise[itemIndex][sampleIndex]
		}
		scoreIndexes := assignChoicesFromScores(scores, quotas)
		choices := make([]int, sampleCount)
		for sampleIndex, scoreIndex := range scoreIndexes {
			choices[sampleIndex] = item.choiceIndexForScore(scoreIndex)
			if reversed[key] {
				responseRows[sampleIndex][itemIndex] = float64(item.OptionCount - scoreIndex)
			} else {
				responseRows[sampleIndex][itemIndex] = float64(scoreIndex + 1)
			}
		}
		choicesByItem[key] = choices
	}
	return cronbachAlpha(responseRows), choicesByItem
}

func (item Item) choiceKey() string {
	return choiceKey(item.QuestionNum, item.RowIndex)
}

func (item Item) choiceIndexForScore(scoreIndex int) int {
	if len(item.ScoreByChoiceIndex) == 0 {
		return clampInt(scoreIndex, 0, item.OptionCount-1)
	}
	for choiceIndex, score := range item.ScoreByChoiceIndex {
		if score == scoreIndex {
			return clampInt(choiceIndex, 0, item.OptionCount-1)
		}
	}
	return clampInt(scoreIndex, 0, item.OptionCount-1)
}

func choiceKey(questionNum int, rowIndex *int) string {
	if rowIndex == nil {
		return "q:" + strconvItoa(questionNum)
	}
	return "q:" + strconvItoa(questionNum) + ":row:" + strconvItoa(*rowIndex)
}

func optionCount(question model.QuestionMeta, entry model.QuestionEntry, rowIndex *int, fallback int) int {
	_ = rowIndex
	if question.Options > 0 {
		return maxInt(2, question.Options)
	}
	if entry.OptionCount > 0 {
		return maxInt(2, entry.OptionCount)
	}
	if values := answerplan.ProbabilityValues(entry.Probabilities); len(values) > 0 {
		return maxInt(2, len(values))
	}
	return maxInt(2, fallback)
}

func probabilitiesForEntry(entry model.QuestionEntry, rowIndex *int, count int) []float64 {
	var values []float64
	if rowIndex != nil {
		values = answerplan.ProbabilityRowValues(entry.Probabilities, *rowIndex)
	}
	if len(values) == 0 {
		values = answerplan.ProbabilityValues(entry.Probabilities)
	}
	if len(values) == 0 {
		return nil
	}
	result := make([]float64, count)
	copy(result, values)
	if positiveTotal(result) <= 0 {
		return nil
	}
	return result
}

func resolveBias(raw string, probabilities []float64, optionCount int) string {
	bias := strings.ToLower(strings.TrimSpace(raw))
	if bias == "left" || bias == "center" || bias == "right" {
		return bias
	}
	if len(probabilities) == 0 {
		return "center"
	}
	normalized := normalizeProbabilityList(probabilities)
	mean := 0.0
	for index, value := range normalized {
		mean += float64(index) * value
	}
	ratio := mean / float64(maxInt(1, optionCount-1))
	if ratio <= 0.4 {
		return "left"
	}
	if ratio >= 0.6 {
		return "right"
	}
	return "center"
}

func normalizeTargetAlpha(value float64) float64 {
	if math.IsNaN(value) || value <= 0 {
		value = defaultTargetAlpha
	}
	if value < minTargetAlpha {
		return minTargetAlpha
	}
	if value > maxTargetAlpha {
		return maxTargetAlpha
	}
	return value
}

func computeRhoFromAlpha(alpha float64, k int) float64 {
	if alpha <= 0 || alpha >= 1 || k < 2 {
		return 0.2
	}
	denom := float64(k) - alpha*float64(k-1)
	if denom <= 0 {
		return 0.2
	}
	rho := alpha / denom
	return math.Max(1e-6, math.Min(0.999999, rho))
}

func computeSigmaEFromAlpha(alpha float64, k int) float64 {
	return math.Sqrt((1 / computeRhoFromAlpha(alpha, k)) - 1)
}

func sigmaCandidates(targetAlpha float64, itemCount int) []float64 {
	base := math.Max(0, computeSigmaEFromAlpha(targetAlpha, itemCount))
	raw := []float64{base * 1.5, base * 1.2, base, base * 0.8, base * 0.6, base * 0.4, base * 0.2, 0.1, 0.05}
	result := make([]float64, 0, len(raw))
	seen := map[float64]bool{}
	for _, value := range raw {
		sigma := math.Round(math.Max(0, value)*1_000_000) / 1_000_000
		if seen[sigma] {
			continue
		}
		seen[sigma] = true
		result = append(result, sigma)
	}
	return result
}

func alphaFitLess(alpha float64, bestAlpha float64, targetAlpha float64) bool {
	if math.IsNaN(alpha) {
		return false
	}
	if math.IsNaN(bestAlpha) {
		return true
	}
	diff := math.Abs(alpha - targetAlpha)
	bestDiff := math.Abs(bestAlpha - targetAlpha)
	if diff != bestDiff {
		return diff < bestDiff
	}
	return alpha <= targetAlpha+1e-6 && bestAlpha > targetAlpha+1e-6
}

func randomVector(count int) []float64 {
	values := make([]float64, count)
	for i := range values {
		values[i] = rand.NormFloat64()
	}
	return values
}

func randomMatrix(rows int, cols int) [][]float64 {
	matrix := make([][]float64, rows)
	for row := range matrix {
		matrix[row] = randomVector(cols)
	}
	return matrix
}

func integerQuotas(probabilities []float64, sampleCount int) []int {
	normalized := normalizeProbabilityList(probabilities)
	if sampleCount <= 0 {
		return make([]int, len(normalized))
	}
	quotas := make([]int, len(normalized))
	remainders := make([]float64, len(normalized))
	total := 0
	for index, value := range normalized {
		raw := value * float64(sampleCount)
		quotas[index] = int(math.Floor(raw))
		remainders[index] = raw - float64(quotas[index])
		total += quotas[index]
	}
	remaining := sampleCount - total
	for remaining > 0 {
		best := 0
		for index := range normalized {
			if remainders[index] > remainders[best] || (remainders[index] == remainders[best] && normalized[index] > normalized[best]) {
				best = index
			}
		}
		quotas[best]++
		remainders[best] = -1
		remaining--
	}
	return quotas
}

func assignChoicesFromScores(scores []float64, quotas []int) []int {
	sampleCount := len(scores)
	orderedChoices := make([]int, 0, sampleCount)
	for optionIndex, quota := range quotas {
		for i := 0; i < quota; i++ {
			orderedChoices = append(orderedChoices, optionIndex)
		}
	}
	for len(orderedChoices) < sampleCount {
		orderedChoices = append(orderedChoices, maxInt(0, len(quotas)-1))
	}
	if len(orderedChoices) > sampleCount {
		orderedChoices = orderedChoices[:sampleCount]
	}
	ranked := make([]int, sampleCount)
	for i := range ranked {
		ranked[i] = i
	}
	for i := 0; i < len(ranked); i++ {
		for j := i + 1; j < len(ranked); j++ {
			if scores[ranked[j]] < scores[ranked[i]] {
				ranked[i], ranked[j] = ranked[j], ranked[i]
			}
		}
	}
	assigned := make([]int, sampleCount)
	for orderIndex, sampleIndex := range ranked {
		assigned[sampleIndex] = orderedChoices[orderIndex]
	}
	return assigned
}

func reversedKeys(items []Item) map[string]bool {
	orientations := make(map[string]string, len(items))
	leftStrength := 0.0
	rightStrength := 0.0
	for _, item := range items {
		direction, strength := itemOrientation(item)
		orientations[item.choiceKey()] = direction
		if direction == "left" {
			leftStrength += strength
		}
		if direction == "right" {
			rightStrength += strength
		}
	}
	anchor := "center"
	anchorStrength := leftStrength
	weaker := rightStrength
	if rightStrength > leftStrength {
		anchor = "right"
		anchorStrength = rightStrength
		weaker = leftStrength
	} else if leftStrength > rightStrength {
		anchor = "left"
	}
	ambiguous := anchor == "center" || anchorStrength < 0.2 || anchorStrength <= weaker*1.15
	result := map[string]bool{}
	if ambiguous {
		return result
	}
	for key, direction := range orientations {
		if (direction == "left" || direction == "right") && direction != anchor {
			result[key] = true
		}
	}
	return result
}

func itemOrientation(item Item) (string, float64) {
	probabilities := normalizeProbabilityList(item.TargetProbabilities)
	mean := 0.0
	for index, value := range probabilities {
		mean += float64(index) * value
	}
	ratio := mean / float64(maxInt(1, item.OptionCount-1))
	direction := "center"
	if ratio <= 0.4 {
		direction = "left"
	} else if ratio >= 0.6 {
		direction = "right"
	}
	return direction, math.Abs(ratio - 0.5)
}

func cronbachAlpha(matrix [][]float64) float64 {
	if len(matrix) == 0 || len(matrix[0]) < 2 {
		return 0
	}
	k := len(matrix[0])
	totals := make([]float64, len(matrix))
	for rowIndex, row := range matrix {
		for _, value := range row {
			totals[rowIndex] += value
		}
	}
	totalVariance := variance(totals)
	if totalVariance == 0 {
		return 0
	}
	itemVariance := 0.0
	for column := 0; column < k; column++ {
		values := make([]float64, len(matrix))
		for rowIndex := range matrix {
			values[rowIndex] = matrix[rowIndex][column]
		}
		itemVariance += variance(values)
	}
	return (float64(k) / float64(k-1)) * (1 - itemVariance/totalVariance)
}

func variance(values []float64) float64 {
	if len(values) < 2 {
		return 0
	}
	mean := 0.0
	for _, value := range values {
		mean += value
	}
	mean /= float64(len(values))
	sum := 0.0
	for _, value := range values {
		delta := value - mean
		sum += delta * delta
	}
	return sum / float64(len(values)-1)
}

func buildBiasTargetProbabilities(optionCount int, bias string) []float64 {
	count := maxInt(2, optionCount)
	if count == 2 {
		switch bias {
		case "left":
			return []float64{0.75, 0.25}
		case "right":
			return []float64{0.25, 0.75}
		default:
			return []float64{0.5, 0.5}
		}
	}
	raw := make([]float64, count)
	for i := 0; i < count; i++ {
		var value float64
		switch bias {
		case "left":
			value = 1 - float64(i)/float64(count-1)
		case "right":
			value = float64(i) / float64(count-1)
		default:
			center := float64(count-1) / 2
			value = 1 - math.Abs(float64(i)-center)/math.Max(center, 1)
		}
		power := 8.0
		if bias == "center" {
			power = 3
		}
		raw[i] = math.Pow(math.Max(value, 0), power)
	}
	return normalizeProbabilityList(raw)
}

func normalizeProbabilityList(values []float64) []float64 {
	cleaned := make([]float64, len(values))
	total := 0.0
	for index, value := range values {
		if math.IsNaN(value) || math.IsInf(value, 0) || value < 0 {
			value = 0
		}
		cleaned[index] = value
		total += value
	}
	if total <= 0 {
		if len(cleaned) == 0 {
			return nil
		}
		for index := range cleaned {
			cleaned[index] = 1 / float64(len(cleaned))
		}
		return cleaned
	}
	for index := range cleaned {
		cleaned[index] /= total
	}
	return cleaned
}

func oneHot(count int, index int) []float64 {
	count = maxInt(1, count)
	values := make([]float64, count)
	values[clampInt(index, 0, count-1)] = 1
	return values
}

func inferOrdinalOptionMapping(optionTexts []string) ([]int, bool) {
	texts := make([]string, 0, len(optionTexts))
	for _, text := range optionTexts {
		normalized := strings.Join(strings.Fields(strings.TrimSpace(text)), "")
		if normalized != "" {
			texts = append(texts, normalized)
		}
	}
	if len(texts) < 2 {
		return nil, false
	}
	if scores, ok := numericOrdinalMapping(texts); ok {
		return scores, true
	}
	groups := [][]string{
		{"非常不满意", "不满意", "一般", "满意", "非常满意"},
		{"非常不同意", "不同意", "一般", "同意", "非常同意"},
		{"很差", "较差", "一般", "较好", "很好"},
		{"从不", "偶尔", "有时", "经常", "总是"},
	}
	for _, group := range groups {
		if len(texts) == len(group) && equalStrings(texts, group) {
			return rangeInts(len(texts)), true
		}
		reversed := reverseStrings(group)
		if len(texts) == len(reversed) && equalStrings(texts, reversed) {
			return reverseInts(len(texts)), true
		}
	}
	return nil, false
}

func numericOrdinalMapping(texts []string) ([]int, bool) {
	re := regexp.MustCompile(`^\d+`)
	values := make([]int, 0, len(texts))
	for _, text := range texts {
		match := re.FindString(text)
		if match == "" {
			return nil, false
		}
		values = append(values, atoi(match))
	}
	if len(values) < 2 {
		return nil, false
	}
	increasing := true
	decreasing := true
	for index := 1; index < len(values); index++ {
		increasing = increasing && values[index] == values[index-1]+1
		decreasing = decreasing && values[index] == values[index-1]-1
	}
	if increasing {
		return rangeInts(len(values)), true
	}
	if decreasing {
		return reverseInts(len(values)), true
	}
	return nil, false
}

func normalizeKind(question model.QuestionMeta, entry model.QuestionEntry) string {
	kind := strings.TrimSpace(entry.QuestionType)
	if kind == "" {
		kind = strings.TrimSpace(question.ProviderType)
	}
	switch kind {
	case "single", "multiple", "dropdown", "scale", "matrix", "order", "slider", "text", "score":
		return kind
	case "radio":
		return "single"
	case "checkbox":
		return "multiple"
	case "select":
		return "dropdown"
	case "matrix_radio":
		return "matrix"
	case "textarea", "multi_text":
		return "text"
	}
	switch question.TypeCode {
	case "3":
		return "single"
	case "4":
		return "multiple"
	case "5":
		return "scale"
	case "6":
		return "matrix"
	case "7":
		return "dropdown"
	case "8":
		return "slider"
	case "11":
		return "order"
	default:
		return "text"
	}
}

func cloneEntries(src []model.QuestionEntry) []model.QuestionEntry {
	dst := make([]model.QuestionEntry, len(src))
	copy(dst, src)
	for i := range dst {
		dst[i].Probabilities = cloneProbabilities(src[i].Probabilities)
		dst[i].Texts = append([]string(nil), src[i].Texts...)
		dst[i].FillableOptionIndices = append([]int(nil), src[i].FillableOptionIndices...)
		dst[i].OptionFillTexts = append([]*string(nil), src[i].OptionFillTexts...)
		dst[i].LocationParts = append([]string(nil), src[i].LocationParts...)
		dst[i].MultiTextBlankModes = append([]string(nil), src[i].MultiTextBlankModes...)
		dst[i].MultiTextBlankAIFlags = append([]bool(nil), src[i].MultiTextBlankAIFlags...)
		dst[i].TextRandomIntRange = append([]int(nil), src[i].TextRandomIntRange...)
	}
	return dst
}

func cloneProbabilities(raw any) any {
	switch values := raw.(type) {
	case []float64:
		return append([]float64(nil), values...)
	case [][]float64:
		cloned := make([][]float64, len(values))
		for i := range values {
			cloned[i] = append([]float64(nil), values[i]...)
		}
		return cloned
	default:
		return raw
	}
}

func cloneIntPtr(value *int) *int {
	if value == nil {
		return nil
	}
	cloned := *value
	return &cloned
}

func equalStrings(left []string, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}

func reverseStrings(values []string) []string {
	result := make([]string, len(values))
	for index := range values {
		result[index] = values[len(values)-1-index]
	}
	return result
}

func rangeInts(count int) []int {
	values := make([]int, count)
	for i := range values {
		values[i] = i
	}
	return values
}

func reverseInts(count int) []int {
	values := make([]int, count)
	for i := range values {
		values[i] = count - 1 - i
	}
	return values
}

func positiveTotal(values []float64) float64 {
	total := 0.0
	for _, value := range values {
		if value > 0 {
			total += value
		}
	}
	return total
}

func atoi(value string) int {
	result := 0
	for _, ch := range value {
		if ch < '0' || ch > '9' {
			break
		}
		result = result*10 + int(ch-'0')
	}
	return result
}

func strconvItoa(value int) string {
	if value == 0 {
		return "0"
	}
	sign := ""
	if value < 0 {
		sign = "-"
		value = -value
	}
	digits := make([]byte, 0, 10)
	for value > 0 {
		digits = append(digits, byte('0'+value%10))
		value /= 10
	}
	for i, j := 0, len(digits)-1; i < j; i, j = i+1, j-1 {
		digits[i], digits[j] = digits[j], digits[i]
	}
	return sign + string(digits)
}

func clampInt(value int, minValue int, maxValue int) int {
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
