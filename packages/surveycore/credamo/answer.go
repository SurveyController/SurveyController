package credamo

import (
	"fmt"
	"sort"

	"surveycontroller/surveycore/internal/model"
)

func buildAnswerItems(rawQuestions []map[string]any, cfg *model.RuntimeConfig) ([]map[string]any, error) {
	entries := indexQuestionEntries(cfg.QuestionEntries)
	items := make([]map[string]any, 0, len(rawQuestions))
	for index, rawQuestion := range rawQuestions {
		questionNum := rawQuestionNum(rawQuestion, index+1)
		entry, ok := entries.find(rawQuestion, questionNum)
		if !ok {
			entry = defaultEntryForRawQuestion(rawQuestion, questionNum)
		}
		item, err := buildAnswerItem(rawQuestion, entry, questionNum)
		if err != nil {
			return nil, err
		}
		item["_sortNo"] = intValue(firstAny(rawQuestion["sortNo"], questionNum))
		items = append(items, item)
	}
	sort.SliceStable(items, func(i int, j int) bool {
		return intValue(items[i]["_sortNo"]) < intValue(items[j]["_sortNo"])
	})
	for _, item := range items {
		delete(item, "_sortNo")
	}
	return items, nil
}

type questionEntryIndex struct {
	byNumber map[int]model.QuestionEntry
	byID     map[string]model.QuestionEntry
}

func indexQuestionEntries(entries []model.QuestionEntry) questionEntryIndex {
	result := questionEntryIndex{
		byNumber: map[int]model.QuestionEntry{},
		byID:     map[string]model.QuestionEntry{},
	}
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

func (idx questionEntryIndex) find(raw map[string]any, questionNum int) (model.QuestionEntry, bool) {
	if id := stringValue(idFromMapping(raw, "qstId", "questionId", "id")); id != "" {
		if entry, ok := idx.byID[id]; ok {
			return entry, true
		}
	}
	entry, ok := idx.byNumber[questionNum]
	return entry, ok
}

func buildAnswerItem(raw map[string]any, entry model.QuestionEntry, questionNum int) (map[string]any, error) {
	switch rawQuestionType(raw) {
	case 1:
		return textAnswer(raw, entry), nil
	case 2:
		return choiceAnswer(raw, entry, questionNum)
	case 4:
		return matrixAnswer(raw, entry, questionNum)
	case 6:
		return orderAnswer(raw, entry, questionNum)
	case 11:
		return choiceAnswer(raw, entry, questionNum)
	default:
		return nil, fmt.Errorf("见数第%d题类型暂不支持纯 HTTP 提交：%d", questionNum, rawQuestionType(raw))
	}
}

func defaultEntryForRawQuestion(raw map[string]any, questionNum int) model.QuestionEntry {
	providerType := rawProviderType(raw)
	optionCount := rawOptionCount(raw)
	return model.QuestionEntry{
		QuestionType:     questionTypeFromProvider(providerType),
		Probabilities:    defaultRawProbabilities(providerType, optionCount),
		OptionCount:      optionCount,
		Rows:             rawRowCount(raw),
		QuestionNum:      &questionNum,
		DistributionMode: "random",
		SurveyProvider:   model.ProviderCredamo,
	}
}

func defaultRawProbabilities(providerType string, optionCount int) any {
	if providerType == "text" || optionCount <= 0 {
		return []float64{1}
	}
	values := make([]float64, optionCount)
	for i := range values {
		values[i] = 1
	}
	return values
}

func questionTypeFromProvider(providerType string) string {
	switch providerType {
	case "single":
		return "single"
	case "multiple":
		return "multiple"
	case "dropdown":
		return "dropdown"
	case "scale":
		return "scale"
	case "matrix":
		return "matrix"
	case "order":
		return "order"
	default:
		return "text"
	}
}

func baseAnswer(raw map[string]any) map[string]any {
	return map[string]any{
		"qstId":         idFromMapping(raw, "qstId", "questionId", "id"),
		"answerTime":    0,
		"answerContent": "",
	}
}

func choiceAnswer(raw map[string]any, entry model.QuestionEntry, questionNum int) (map[string]any, error) {
	choices := asMapList(raw["choices"])
	if len(choices) == 0 {
		return nil, fmt.Errorf("见数第%d题缺少选项", questionNum)
	}
	item := baseAnswer(raw)
	if rawSelector(raw) == 2 || entry.QuestionType == "multiple" {
		selected := selectedIndices(entry, len(choices), true)
		values := make([]map[string]any, 0, len(selected))
		for _, index := range selected {
			values = append(values, choicePayload(choices[index], ""))
		}
		item["answerQstChoiceList"] = values
		return item, nil
	}
	index := selectedIndex(entry, len(choices))
	item["answerQstChoice"] = choicePayload(choices[index], fillTextAt(entry.OptionFillTexts, index))
	return item, nil
}

func textAnswer(raw map[string]any, entry model.QuestionEntry) map[string]any {
	item := baseAnswer(raw)
	text := "无"
	if len(entry.Texts) > 0 && entry.Texts[0] != "" {
		text = entry.Texts[0]
	}
	item["answerContent"] = text
	return item
}

func matrixAnswer(raw map[string]any, entry model.QuestionEntry, questionNum int) (map[string]any, error) {
	rows := asMapList(raw["choices"])
	columns := asMapList(raw["answers"])
	if len(rows) == 0 || len(columns) == 0 {
		return nil, fmt.Errorf("见数第%d题缺少矩阵行列", questionNum)
	}
	item := baseAnswer(raw)
	answerRows := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		colIndex := selectedIndex(entry, len(columns))
		answerRows = append(answerRows, map[string]any{
			"choiceId": idFromMapping(row, "choiceId", "id"),
			"choiceAnswerList": []map[string]any{
				{"answerId": idFromMapping(columns[colIndex], "answerId", "id")},
			},
		})
	}
	item["answerQstChoiceList"] = answerRows
	return item, nil
}

func orderAnswer(raw map[string]any, entry model.QuestionEntry, questionNum int) (map[string]any, error) {
	choices := asMapList(raw["choices"])
	if len(choices) == 0 {
		return nil, fmt.Errorf("见数第%d题缺少排序选项", questionNum)
	}
	item := baseAnswer(raw)
	indices := selectedIndices(entry, len(choices), true)
	if len(indices) == 0 {
		for index := range choices {
			indices = append(indices, index)
		}
	}
	ranked := make([]map[string]any, 0, len(indices))
	for rank, index := range indices {
		ranked = append(ranked, map[string]any{
			"choiceId":      idFromMapping(choices[index], "choiceId", "id"),
			"choiceContent": rank + 1,
		})
	}
	item["answerChoiceContent"] = ranked
	return item, nil
}
