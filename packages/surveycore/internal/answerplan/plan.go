package answerplan

import (
	"encoding/json"
	"fmt"
	"math"
	"math/rand"
	"strconv"
	"strings"

	"surveycontroller/surveycore/internal/model"
)

type Action struct {
	QuestionNum     int
	QuestionID      string
	Kind            string
	SelectedIndices []int
	MatrixIndices   []int
	TextValues      []string
	SliderValue     string
	OptionFillTexts map[int]string
}

type EntryIndex struct {
	byNumber map[int]model.QuestionEntry
	byID     map[string]model.QuestionEntry
}

func NewEntryIndex(entries []model.QuestionEntry) EntryIndex {
	result := EntryIndex{byNumber: map[int]model.QuestionEntry{}, byID: map[string]model.QuestionEntry{}}
	for _, entry := range entries {
		if entry.QuestionNum != nil {
			result.byNumber[*entry.QuestionNum] = entry
		}
		if entry.ProviderQuestionID != nil && strings.TrimSpace(*entry.ProviderQuestionID) != "" {
			result.byID[strings.TrimSpace(*entry.ProviderQuestionID)] = entry
		}
	}
	return result
}

func (idx EntryIndex) Find(question model.QuestionMeta) (model.QuestionEntry, bool) {
	if question.ProviderID != "" {
		if entry, ok := idx.byID[question.ProviderID]; ok {
			return entry, true
		}
	}
	entry, ok := idx.byNumber[question.Num]
	return entry, ok
}

func BuildAction(question model.QuestionMeta, entry model.QuestionEntry) (Action, error) {
	action := Action{
		QuestionNum:     question.Num,
		QuestionID:      question.ProviderID,
		Kind:            entry.QuestionType,
		OptionFillTexts: map[int]string{},
	}
	kind := normalizeKind(question, entry)
	switch kind {
	case "single", "dropdown", "scale":
		index := SelectedIndex(entry, maxInt(1, question.Options))
		if question.ForcedOptionIdx != nil {
			index = minInt(maxInt(0, *question.ForcedOptionIdx), maxInt(0, question.Options-1))
		}
		action.Kind = kind
		action.SelectedIndices = []int{index}
		if fill := FillTextAt(entry.OptionFillTexts, index); fill != "" {
			action.OptionFillTexts[index] = fill
		}
	case "multiple":
		minRequired := 1
		if question.MultiMinLimit != nil {
			minRequired = *question.MultiMinLimit
		}
		maxAllowed := question.Options
		if question.MultiMaxLimit != nil {
			maxAllowed = *question.MultiMaxLimit
		}
		action.Kind = kind
		action.SelectedIndices = SelectedIndices(entry, maxInt(1, question.Options), minRequired, maxAllowed)
		for _, index := range action.SelectedIndices {
			if fill := FillTextAt(entry.OptionFillTexts, index); fill != "" {
				action.OptionFillTexts[index] = fill
			}
		}
	case "matrix":
		action.Kind = kind
		for row := 0; row < maxInt(1, question.Rows); row++ {
			action.MatrixIndices = append(action.MatrixIndices, SelectedIndex(entry, maxInt(1, question.Options)))
		}
	case "order":
		action.Kind = kind
		for index := 0; index < maxInt(1, question.Options); index++ {
			action.SelectedIndices = append(action.SelectedIndices, index)
		}
	case "slider":
		action.Kind = kind
		action.SliderValue = firstNonEmpty(stringValue(question.SliderMin), "50")
	default:
		action.Kind = "text"
		count := maxInt(1, question.TextInputs)
		text := firstNonEmpty(firstText(entry.Texts), firstText(question.ForcedTexts), "无")
		for index := 0; index < count; index++ {
			action.TextValues = append(action.TextValues, firstNonEmpty(textAt(entry.Texts, index), textAt(question.ForcedTexts, index), text))
		}
	}
	if action.QuestionNum <= 0 {
		return Action{}, fmt.Errorf("题目编号无效")
	}
	return action, nil
}

func normalizeKind(question model.QuestionMeta, entry model.QuestionEntry) string {
	kind := strings.TrimSpace(entry.QuestionType)
	if kind == "" {
		kind = strings.TrimSpace(question.ProviderType)
	}
	switch kind {
	case "single", "multiple", "dropdown", "scale", "matrix", "order", "slider", "text", "multi_text":
		if kind == "multi_text" {
			return "text"
		}
		return kind
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
	values := ProbabilityValues(entry.Probabilities)
	selected := make([]int, 0)
	for index, value := range values {
		if index < count && value > 0 {
			selected = append(selected, index)
		}
	}
	if len(selected) == 0 {
		selected = append(selected, 0)
	}
	for index := 0; index < count && len(selected) < minRequired; index++ {
		if !containsIndex(selected, index) {
			selected = append(selected, index)
		}
	}
	if len(selected) > maxAllowed {
		selected = selected[:maxAllowed]
	}
	return selected
}

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

func FillTextAt(values []*string, index int) string {
	if index < 0 || index >= len(values) || values[index] == nil {
		return ""
	}
	return strings.TrimSpace(*values[index])
}

func containsIndex(values []int, target int) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func firstText(values []string) string {
	for _, value := range values {
		if text := strings.TrimSpace(value); text != "" {
			return text
		}
	}
	return ""
}

func textAt(values []string, index int) string {
	if index < 0 || index >= len(values) {
		return ""
	}
	return strings.TrimSpace(values[index])
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
