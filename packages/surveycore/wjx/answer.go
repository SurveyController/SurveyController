package wjx

import (
	"fmt"
	"sort"
	"strconv"
	"strings"

	"surveycontroller/surveycore/internal/model"
)

type answerAction struct {
	QuestionNum int
	Kind        string
	Indices     []int
	Matrix      []int
	Texts       []string
	SliderValue string
	OptionFills map[int]string
}

func buildSubmitData(questions []model.QuestionMeta, cfg *model.RuntimeConfig) (string, error) {
	entries := indexEntries(cfg.QuestionEntries)
	actions := make([]answerAction, 0, len(questions))
	for _, question := range questions {
		if question.IsDescription {
			continue
		}
		entry, ok := entries.find(question)
		if !ok {
			entry = defaultEntry(question)
		}
		action, err := buildAction(question, entry)
		if err != nil {
			return "", err
		}
		if action.QuestionNum > 0 && actionAnswer(action) != "" {
			actions = append(actions, action)
		}
	}
	sort.SliceStable(actions, func(i int, j int) bool { return actions[i].QuestionNum < actions[j].QuestionNum })
	parts := make([]string, 0, len(actions))
	for _, action := range actions {
		answer := strings.ReplaceAll(actionAnswer(action), "，", ",")
		if answer != "" {
			parts = append(parts, fmt.Sprintf("%d$%s", action.QuestionNum, answer))
		}
	}
	if len(parts) == 0 {
		return "", fmt.Errorf("问卷星没有生成可提交答案")
	}
	return strings.Join(parts, "}"), nil
}

type entryIndex struct {
	byNumber map[int]model.QuestionEntry
	byID     map[string]model.QuestionEntry
}

func indexEntries(entries []model.QuestionEntry) entryIndex {
	result := entryIndex{byNumber: map[int]model.QuestionEntry{}, byID: map[string]model.QuestionEntry{}}
	for _, entry := range entries {
		if entry.QuestionNum != nil {
			result.byNumber[*entry.QuestionNum] = entry
		}
		if entry.ProviderQuestionID != nil && *entry.ProviderQuestionID != "" {
			result.byID[*entry.ProviderQuestionID] = entry
		}
	}
	return result
}

func (idx entryIndex) find(question model.QuestionMeta) (model.QuestionEntry, bool) {
	if question.ProviderID != "" {
		if entry, ok := idx.byID[question.ProviderID]; ok {
			return entry, true
		}
	}
	entry, ok := idx.byNumber[question.Num]
	return entry, ok
}

func defaultEntry(question model.QuestionMeta) model.QuestionEntry {
	num := question.Num
	providerID := question.ProviderID
	return model.QuestionEntry{
		QuestionType:       question.ProviderType,
		Probabilities:      defaultProbabilities(question),
		Rows:               question.Rows,
		OptionCount:        maxInt(1, question.Options),
		QuestionNum:        &num,
		SurveyProvider:     model.ProviderWJX,
		ProviderQuestionID: &providerID,
	}
}

func defaultProbabilities(question model.QuestionMeta) []float64 {
	count := maxInt(1, question.Options)
	values := make([]float64, count)
	for i := range values {
		values[i] = 1
	}
	return values
}

func buildAction(question model.QuestionMeta, entry model.QuestionEntry) (answerAction, error) {
	action := answerAction{QuestionNum: question.Num, Kind: entry.QuestionType, OptionFills: map[int]string{}}
	switch question.ProviderType {
	case "single", "dropdown", "scale":
		index := selectedIndex(entry, maxInt(1, question.Options))
		if question.ForcedOptionIdx != nil {
			index = minInt(maxInt(0, *question.ForcedOptionIdx), maxInt(0, question.Options-1))
		}
		action.Kind = "choice"
		action.Indices = []int{index}
		if fill := fillTextAt(entry.OptionFillTexts, index); fill != "" {
			action.OptionFills[index] = fill
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
		action.Kind = "choice"
		action.Indices = selectedIndices(entry, maxInt(1, question.Options), minRequired, maxAllowed)
		for _, index := range action.Indices {
			if fill := fillTextAt(entry.OptionFillTexts, index); fill != "" {
				action.OptionFills[index] = fill
			}
		}
	case "matrix":
		action.Kind = "matrix"
		rows := maxInt(1, question.Rows)
		options := maxInt(1, question.Options)
		for row := 0; row < rows; row++ {
			action.Matrix = append(action.Matrix, selectedIndex(entry, options))
		}
	case "order":
		action.Kind = "order"
		for index := 0; index < maxInt(1, question.Options); index++ {
			action.Indices = append(action.Indices, index)
		}
	case "slider":
		action.Kind = "slider"
		action.SliderValue = "50"
	default:
		action.Kind = "text"
		count := maxInt(1, question.TextInputs)
		text := "无"
		if len(entry.Texts) > 0 && strings.TrimSpace(entry.Texts[0]) != "" {
			text = strings.TrimSpace(entry.Texts[0])
		}
		for index := 0; index < count; index++ {
			if index < len(entry.Texts) && strings.TrimSpace(entry.Texts[index]) != "" {
				action.Texts = append(action.Texts, strings.TrimSpace(entry.Texts[index]))
			} else {
				action.Texts = append(action.Texts, text)
			}
		}
	}
	return action, nil
}

func actionAnswer(action answerAction) string {
	switch action.Kind {
	case "choice", "select":
		parts := make([]string, 0, len(action.Indices))
		for _, index := range action.Indices {
			value := strconv.Itoa(index + 1)
			if fill := strings.TrimSpace(action.OptionFills[index]); fill != "" {
				value += "!" + fill
			}
			parts = append(parts, value)
		}
		return strings.Join(parts, "|")
	case "matrix":
		parts := make([]string, 0, len(action.Matrix))
		for row, index := range action.Matrix {
			parts = append(parts, fmt.Sprintf("%d!%d", row+1, index+1))
		}
		return strings.Join(parts, ",")
	case "text":
		return strings.Join(action.Texts, "^")
	case "slider":
		return action.SliderValue
	case "order":
		parts := make([]string, 0, len(action.Indices))
		for _, index := range action.Indices {
			parts = append(parts, strconv.Itoa(index+1))
		}
		return strings.Join(parts, ",")
	default:
		return ""
	}
}

func fillTextAt(values []*string, index int) string {
	if index < 0 || index >= len(values) || values[index] == nil {
		return ""
	}
	return strings.TrimSpace(*values[index])
}
