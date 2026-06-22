package credamo

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

var digitRE = regexp.MustCompile(`\d+`)

func asMapList(value any) []map[string]any {
	raw, ok := value.([]any)
	if !ok {
		return nil
	}
	result := make([]map[string]any, 0, len(raw))
	for _, item := range raw {
		if mapped, ok := item.(map[string]any); ok {
			result = append(result, mapped)
		}
	}
	return result
}

func iterRawQuestions(detail map[string]any) []map[string]any {
	result := make([]map[string]any, 0)
	if direct := asMapList(detail["questions"]); len(direct) > 0 {
		result = append(result, direct...)
	}
	for _, block := range asMapList(detail["blocks"]) {
		for _, element := range asMapList(firstAny(block["blockElements"], block["elements"])) {
			candidates := []any{
				element["question"],
				element["qst"],
				element["surveyQuestion"],
				element,
			}
			for _, candidate := range candidates {
				mapped, ok := candidate.(map[string]any)
				if !ok {
					continue
				}
				if mapped["qstId"] != nil || mapped["questionId"] != nil || mapped["questionType"] != nil {
					result = append(result, mapped)
					break
				}
			}
		}
	}
	return result
}

func rawQuestionNum(raw map[string]any, fallback int) int {
	for _, key := range []string{"qstNo", "questionNo", "qstNum", "sortNo"} {
		match := digitRE.FindString(fmt.Sprint(raw[key]))
		if match == "" {
			continue
		}
		number, err := strconv.Atoi(match)
		if err == nil && number > 0 {
			return number
		}
	}
	if fallback > 0 {
		return fallback
	}
	return 1
}

func rawQuestionType(raw map[string]any) int {
	return intValue(raw["questionType"])
}

func rawSelector(raw map[string]any) int {
	return intValue(raw["selector"])
}

func rawProviderType(raw map[string]any) string {
	questionType := rawQuestionType(raw)
	selector := rawSelector(raw)
	switch {
	case questionType == 2 && selector == 2:
		return "multiple"
	case questionType == 2 && selector == 3:
		return "dropdown"
	case questionType == 2:
		return "single"
	case questionType == 4:
		return "matrix"
	case questionType == 6:
		return "order"
	case questionType == 11:
		return "scale"
	case questionType == 1:
		return "text"
	default:
		if questionType > 0 {
			return strconv.Itoa(questionType)
		}
		return ""
	}
}

func rawOptionCount(raw map[string]any) int {
	switch rawQuestionType(raw) {
	case 4:
		return len(asMapList(raw["answers"]))
	case 1:
		return 1
	default:
		return len(asMapList(raw["choices"]))
	}
}

func rawRowCount(raw map[string]any) int {
	if rawQuestionType(raw) == 4 {
		if count := len(asMapList(raw["choices"])); count > 0 {
			return count
		}
	}
	return 1
}

func rawToNormalizedInput(raw map[string]any, fallbackNum int) map[string]any {
	providerType := rawProviderType(raw)
	questionNum := rawQuestionNum(raw, fallbackNum)
	qstNo := firstString(raw["qstNo"], raw["questionNo"], raw["qstNum"], raw["sortNo"])
	if qstNo == "" {
		qstNo = fmt.Sprintf("Q%d", questionNum)
	}
	titleText := firstString(raw["qstTitle"], raw["qstName"], raw["questionTitle"], raw["questionName"], raw["title"], raw["name"], raw["content"], raw["display"])
	fullTitle := titleText
	if titleText != "" && !strings.HasPrefix(titleText, qstNo) {
		fullTitle = normalizeText(qstNo + " " + titleText)
	}
	if fullTitle == "" {
		fullTitle = qstNo
	}

	choices := asMapList(raw["choices"])
	answers := asMapList(raw["answers"])
	questionType := rawQuestionType(raw)
	var optionSource []map[string]any
	if questionType == 4 {
		optionSource = answers
	} else {
		optionSource = choices
	}
	optionTexts := itemTexts(optionSource, "display", "answerContent", "choiceContent", "choiceTitle", "answerTitle", "content", "text", "title", "name")
	rowTexts := []string{}
	if questionType == 4 {
		rowTexts = itemTexts(choices, "display", "choiceContent", "choiceTitle", "content", "text", "title", "name")
	}
	if len(optionTexts) == 0 {
		for i := 0; i < rawOptionCount(raw); i++ {
			optionTexts = append(optionTexts, fmt.Sprintf("选项 %d", i+1))
		}
	}
	if questionType == 4 && len(rowTexts) == 0 {
		for i := 0; i < rawRowCount(raw); i++ {
			rowTexts = append(rowTexts, fmt.Sprintf("第 %d 行", i+1))
		}
	}
	textInputs := 0
	if questionType == 1 {
		textInputs = 1
	}
	return map[string]any{
		"question_num":        qstNo,
		"title":               fullTitle,
		"title_full_text":     fullTitle,
		"title_text":          titleText,
		"tip_text":            firstString(raw["tip"], raw["tips"], raw["remark"], raw["description"]),
		"question_kind":       providerType,
		"provider_type":       providerType,
		"option_texts":        optionTexts,
		"matrix_column_texts": optionTexts,
		"row_texts":           rowTexts,
		"text_inputs":         textInputs,
		"page":                firstAny(raw["page"], raw["pageNo"], 1),
		"question_id":         firstString(raw["questionId"], raw["qstId"], raw["id"], strconv.Itoa(questionNum)),
		"required":            boolValue(firstAny(raw["required"], raw["mustAnswer"])),
	}
}

func surveyTitle(detail map[string]any) string {
	if title := firstString(detail["surveyTitle"], detail["title"], detail["name"], detail["projectName"]); title != "" {
		return title
	}
	if survey, ok := detail["survey"].(map[string]any); ok {
		if title := firstString(survey["surveyTitle"], survey["title"], survey["name"]); title != "" {
			return title
		}
	}
	return "Credamo 见数问卷"
}
