package answerplan

import (
	"strconv"
	"strings"

	"surveycontroller/surveycore/internal/model"
)

const (
	conditionSelected    = "selected"
	conditionNotSelected = "not_selected"
	actionMustSelect     = "must_select"
	actionMustNotSelect  = "must_not_select"
)

type answerRule struct {
	id                     string
	conditionQuestionNum   int
	conditionMode          string
	conditionOptionIndices []int
	conditionRowIndex      *int
	targetQuestionNum      int
	targetMode             string
	targetOptionIndices    []int
	targetRowIndex         *int
}

type answerRecord struct {
	selected []int
	rows     map[int][]int
}

type consistencyPlan struct {
	rules    []answerRule
	answered map[int]answerRecord
}

func newConsistencyPlan(raw []map[string]any) *consistencyPlan {
	return &consistencyPlan{
		rules:    parseRules(raw),
		answered: map[int]answerRecord{},
	}
}

func (p *consistencyPlan) apply(question model.QuestionMeta, entry model.QuestionEntry) model.QuestionEntry {
	if p == nil || len(p.rules) == 0 {
		return entry
	}
	kind := normalizeKind(question, entry)
	switch kind {
	case "single", "dropdown", "scale":
		return p.applySingleLike(question.Num, entry, nil)
	case "matrix":
		return p.applyMatrix(question, entry)
	case "multiple":
		return p.applyMultiple(question, entry)
	default:
		return entry
	}
}

func (p *consistencyPlan) applySingleLike(questionNum int, entry model.QuestionEntry, rowIndex *int) model.QuestionEntry {
	rule := p.latestTriggeredRule(questionNum, rowIndex)
	if rule == nil {
		return entry
	}
	values := ProbabilityValues(entry.Probabilities)
	adjusted, ok := applyRuleToProbabilities(values, *rule)
	if !ok {
		return entry
	}
	entry.Probabilities = adjusted
	return entry
}

func (p *consistencyPlan) applyMatrix(question model.QuestionMeta, entry model.QuestionEntry) model.QuestionEntry {
	rows := maxInt(1, question.Rows)
	options := maxInt(1, question.Options)
	matrix := make([][]float64, rows)
	changed := false
	for row := 0; row < rows; row++ {
		rowIndex := row
		values := ProbabilityRowValues(entry.Probabilities, row)
		if len(values) == 0 {
			values = ProbabilityValues(entry.Probabilities)
		}
		values = fitProbabilityCount(values, options)
		rule := p.latestTriggeredRule(question.Num, &rowIndex)
		if rule != nil {
			if adjusted, ok := applyRuleToProbabilities(values, *rule); ok {
				values = adjusted
				changed = true
			}
		}
		matrix[row] = values
	}
	if changed {
		entry.Probabilities = matrix
	}
	return entry
}

func (p *consistencyPlan) applyMultiple(question model.QuestionMeta, entry model.QuestionEntry) model.QuestionEntry {
	rule := p.latestTriggeredRule(question.Num, nil)
	if rule == nil {
		return entry
	}
	count := maxInt(1, maxInt(question.Options, entry.OptionCount))
	values := fitProbabilityCount(ProbabilityValues(entry.Probabilities), count)
	adjusted, ok := applyRuleToMultipleProbabilities(values, *rule)
	if !ok {
		return entry
	}
	entry.Probabilities = adjusted
	return entry
}

func (p *consistencyPlan) record(action Action) {
	if p == nil || action.QuestionNum <= 0 {
		return
	}
	record := answerRecord{selected: append([]int(nil), action.SelectedIndices...), rows: map[int][]int{}}
	for rowIndex, optionIndex := range action.MatrixIndices {
		record.rows[rowIndex] = []int{optionIndex}
	}
	p.answered[action.QuestionNum] = record
}

func (p *consistencyPlan) latestTriggeredRule(questionNum int, rowIndex *int) *answerRule {
	if p == nil {
		return nil
	}
	var selected *answerRule
	for i := range p.rules {
		rule := &p.rules[i]
		if rule.targetQuestionNum != questionNum {
			continue
		}
		if !sameOptionalInt(rule.targetRowIndex, rowIndex) {
			continue
		}
		if p.ruleTriggered(*rule) {
			selected = rule
		}
	}
	return selected
}

func (p *consistencyPlan) ruleTriggered(rule answerRule) bool {
	if rule.conditionQuestionNum >= rule.targetQuestionNum {
		return false
	}
	record, ok := p.answered[rule.conditionQuestionNum]
	if !ok {
		return false
	}
	var selected []int
	if rule.conditionRowIndex != nil {
		selected = record.rows[*rule.conditionRowIndex]
	} else {
		selected = record.selected
	}
	if len(selected) == 0 || len(rule.conditionOptionIndices) == 0 {
		return false
	}
	overlap := intersects(selected, rule.conditionOptionIndices)
	if rule.conditionMode == conditionSelected {
		return overlap
	}
	if rule.conditionMode == conditionNotSelected {
		return !overlap
	}
	return false
}

func applyRuleToProbabilities(values []float64, rule answerRule) ([]float64, bool) {
	if len(values) == 0 || len(rule.targetOptionIndices) == 0 {
		return nil, false
	}
	targets := map[int]bool{}
	for _, index := range rule.targetOptionIndices {
		if index >= 0 && index < len(values) {
			targets[index] = true
		}
	}
	if len(targets) == 0 {
		return nil, false
	}
	adjusted := make([]float64, len(values))
	switch rule.targetMode {
	case actionMustSelect:
		for index, value := range values {
			if targets[index] {
				adjusted[index] = value
			}
		}
	case actionMustNotSelect:
		for index, value := range values {
			if !targets[index] {
				adjusted[index] = value
			}
		}
	default:
		return nil, false
	}
	if positiveTotal(adjusted) <= 0 {
		return nil, false
	}
	return adjusted, true
}

func applyRuleToMultipleProbabilities(values []float64, rule answerRule) ([]float64, bool) {
	if len(values) == 0 || len(rule.targetOptionIndices) == 0 {
		return nil, false
	}
	targets := map[int]bool{}
	for _, index := range rule.targetOptionIndices {
		if index >= 0 && index < len(values) {
			targets[index] = true
		}
	}
	if len(targets) == 0 {
		return nil, false
	}
	adjusted := append([]float64(nil), values...)
	switch rule.targetMode {
	case actionMustSelect:
		for index := range targets {
			adjusted[index] = 100
		}
	case actionMustNotSelect:
		for index := range targets {
			adjusted[index] = 0
		}
	default:
		return nil, false
	}
	if positiveTotal(adjusted) <= 0 {
		return nil, false
	}
	return adjusted, true
}

func parseRules(raw []map[string]any) []answerRule {
	rules := make([]answerRule, 0, len(raw))
	for _, item := range raw {
		rule, ok := parseRule(item)
		if ok {
			rules = append(rules, rule)
		}
	}
	return rules
}

func parseRule(raw map[string]any) (answerRule, bool) {
	if raw == nil {
		return answerRule{}, false
	}
	conditionQuestionNum := intValue(raw["condition_question_num"], -1)
	targetQuestionNum := intValue(raw["target_question_num"], -1)
	conditionMode := strings.TrimSpace(stringValue(raw["condition_mode"]))
	targetMode := strings.TrimSpace(stringValue(raw["action_mode"]))
	if conditionQuestionNum <= 0 || targetQuestionNum <= 0 {
		return answerRule{}, false
	}
	if conditionMode != conditionSelected && conditionMode != conditionNotSelected {
		return answerRule{}, false
	}
	if targetMode != actionMustSelect && targetMode != actionMustNotSelect {
		return answerRule{}, false
	}
	conditionIndices := intList(raw["condition_option_indices"])
	targetIndices := intList(raw["target_option_indices"])
	if len(conditionIndices) == 0 || len(targetIndices) == 0 {
		return answerRule{}, false
	}
	return answerRule{
		id:                     strings.TrimSpace(stringValue(raw["id"])),
		conditionQuestionNum:   conditionQuestionNum,
		conditionMode:          conditionMode,
		conditionOptionIndices: conditionIndices,
		conditionRowIndex:      optionalInt(raw["condition_row_index"]),
		targetQuestionNum:      targetQuestionNum,
		targetMode:             targetMode,
		targetOptionIndices:    targetIndices,
		targetRowIndex:         optionalInt(raw["target_row_index"]),
	}, true
}

func fitProbabilityCount(values []float64, count int) []float64 {
	if count <= 0 {
		return nil
	}
	result := make([]float64, count)
	copy(result, values)
	if positiveTotal(result) <= 0 {
		for i := range result {
			result[i] = 1
		}
	}
	return result
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

func intersects(left []int, right []int) bool {
	seen := map[int]bool{}
	for _, value := range left {
		seen[value] = true
	}
	for _, value := range right {
		if seen[value] {
			return true
		}
	}
	return false
}

func intList(raw any) []int {
	rawList, ok := raw.([]any)
	if !ok {
		if typed, ok := raw.([]int); ok {
			return uniqueSortedInts(typed)
		}
		return nil
	}
	values := make([]int, 0, len(rawList))
	for _, item := range rawList {
		value := intValue(item, -1)
		if value >= 0 {
			values = append(values, value)
		}
	}
	return uniqueSortedInts(values)
}

func uniqueSortedInts(values []int) []int {
	seen := map[int]bool{}
	result := make([]int, 0, len(values))
	for _, value := range values {
		if value < 0 || seen[value] {
			continue
		}
		seen[value] = true
		result = append(result, value)
	}
	for i := 0; i < len(result); i++ {
		for j := i + 1; j < len(result); j++ {
			if result[j] < result[i] {
				result[i], result[j] = result[j], result[i]
			}
		}
	}
	return result
}

func optionalInt(raw any) *int {
	if raw == nil {
		return nil
	}
	value := intValue(raw, -1)
	if value < 0 {
		return nil
	}
	return &value
}

func sameOptionalInt(left *int, right *int) bool {
	if left == nil || right == nil {
		return left == nil && right == nil
	}
	return *left == *right
}

func intValue(raw any, fallback int) int {
	switch value := raw.(type) {
	case int:
		return value
	case int64:
		return int(value)
	case float64:
		return int(value)
	case float32:
		return int(value)
	case string:
		parsed, err := strconv.Atoi(strings.TrimSpace(value))
		if err == nil {
			return parsed
		}
	}
	return fallback
}
