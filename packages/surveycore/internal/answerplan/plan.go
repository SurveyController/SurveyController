package answerplan

import (
	"fmt"
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
	return BuildActionWithOptions(question, entry, BuildOptions{})
}

func BuildActionWithOptions(question model.QuestionMeta, entry model.QuestionEntry, options BuildOptions) (Action, error) {
	action := Action{
		QuestionNum:     question.Num,
		QuestionID:      question.ProviderID,
		Kind:            entry.QuestionType,
		OptionFillTexts: map[int]string{},
	}
	kind := normalizeKind(question, entry)
	switch kind {
	case "single", "dropdown", "scale":
		count := maxInt(1, question.Options)
		selectionEntry, trackDistribution := selectionEntry(question, entry, nil, count, options)
		index := SelectedIndex(selectionEntry, count)
		if question.ForcedOptionIdx != nil {
			index = minInt(maxInt(0, *question.ForcedOptionIdx), maxInt(0, question.Options-1))
			trackDistribution = false
		}
		action.Kind = kind
		action.SelectedIndices = []int{index}
		if fill := OptionFillText(entry, question, index); fill != "" {
			action.OptionFillTexts[index] = fill
		}
		if trackDistribution {
			recordPendingDistribution(options, question.Num, nil, index, count)
		}
	case "multiple":
		entry = multipleSelectionEntry(question, entry, options)
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
			if fill := OptionFillText(entry, question, index); fill != "" {
				action.OptionFillTexts[index] = fill
			}
		}
	case "matrix":
		action.Kind = kind
		for row := 0; row < maxInt(1, question.Rows); row++ {
			rowIndex := row
			count := maxInt(1, question.Options)
			selectionEntry, trackDistribution := selectionEntry(question, entry, &rowIndex, count, options)
			index := SelectedMatrixIndex(selectionEntry, row, count)
			action.MatrixIndices = append(action.MatrixIndices, index)
			if trackDistribution {
				recordPendingDistribution(options, question.Num, &rowIndex, index, count)
			}
		}
	case "order":
		action.Kind = kind
		for index := 0; index < maxInt(1, question.Options); index++ {
			action.SelectedIndices = append(action.SelectedIndices, index)
		}
	case "slider":
		action.Kind = kind
		action.SliderValue = firstNonEmpty(stringValue(firstProbabilityValue(entry.Probabilities)), stringValue(question.SliderMin), defaultSliderValue)
	default:
		action.Kind = "text"
		count := maxInt(1, question.TextInputs)
		action.TextValues = ResolveTextValuesWithPersona(entry, question, count, options.Persona)
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
