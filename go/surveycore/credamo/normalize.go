package credamo

import (
	"regexp"
	"strconv"
	"strings"

	"surveycontroller/surveycore/internal/model"
)

var (
	htmlTagRE             = regexp.MustCompile(`<[^>]+>`)
	spaceRE               = regexp.MustCompile(`\s+`)
	questionNumberRE      = regexp.MustCompile(`^\s*(?:Q|题目?)\s*(\d+)\b`)
	leadingTypeTagRE      = regexp.MustCompile(`^(?:(?:\[[^\]]+\]|【[^】]+】)\s*)+`)
	typeOnlyTitleRE       = regexp.MustCompile(`^\s*\[[^\]]+\]\s*$`)
	genericMatrixOptionRE = regexp.MustCompile(`(?i)^选项\s*\d+$`)
)

func normalizeQuestion(raw map[string]any, fallbackNum int) model.QuestionMeta {
	rawTitle := normalizeText(firstAny(raw["title_full_text"], raw["title"]))
	questionNum := normalizeQuestionNumber(raw["question_num"], fallbackNum)
	title := rawTitle
	if match := questionNumberRE.FindStringSubmatch(rawTitle); len(match) > 1 {
		questionNum = normalizeQuestionNumber(match[1], fallbackNum)
		stripped := normalizeText(leadingTypeTagRE.ReplaceAllString(strings.TrimSpace(rawTitle[len(match[0]):]), ""))
		if stripped != "" && !typeOnlyTitleRE.MatchString(stripped) {
			title = stripped
		}
	}
	if title == "" {
		title = "Q" + strconv.Itoa(questionNum)
	}

	optionTexts := cleanTextList(stringList(raw["option_texts"]))
	optionTexts = resolveMatrixOptionTexts(raw, optionTexts)
	rowTexts := cleanTextList(stringList(raw["row_texts"]))
	textInputs := intValue(raw["text_inputs"])
	questionKind := strings.ToLower(strings.TrimSpace(stringValue(raw["question_kind"])))
	typeCode := inferTypeCode(questionKind, len(optionTexts), textInputs)
	isDescription := !(len(optionTexts) > 0 || textInputs > 0 || containsString([]string{"single", "multiple", "dropdown", "scale", "order", "matrix", "text", "multi_text"}, questionKind))
	if isDescription {
		typeCode = "0"
	}

	ratingMax := 0
	if typeCode == "5" {
		ratingMax = len(optionTexts)
		if ratingMax < 1 {
			ratingMax = 1
		}
	}

	return model.QuestionMeta{
		Num:             questionNum,
		Title:           title,
		Description:     "",
		TypeCode:        typeCode,
		Options:         len(optionTexts),
		Rows:            maxInt(1, len(rowTexts)),
		RowTexts:        rowTexts,
		Page:            maxInt(1, intValue(raw["page"])),
		OptionTexts:     optionTexts,
		Provider:        model.ProviderCredamo,
		ProviderID:      stringValue(firstAny(raw["question_id"], questionNum)),
		ProviderPageID:  stringValue(firstAny(raw["page"], 1)),
		ProviderType:    strings.TrimSpace(stringValue(firstAny(raw["provider_type"], questionKind, typeCode))),
		Required:        boolValue(raw["required"]),
		IsDescription:   isDescription,
		IsRating:        false,
		RatingMax:       ratingMax,
		TextInputs:      maxInt(0, textInputs),
		IsTextLike:      questionKind == "text" || questionKind == "multi_text" || (textInputs > 0 && len(optionTexts) == 0),
		IsMultiText:     questionKind == "multi_text" || textInputs > 1,
		LogicStatus:     model.LogicParseStatusNone,
		ForcedTexts:     []string{},
		FillableOptions: intList(raw["fillable_options"]),
	}
}

func normalizeText(value any) string {
	text := strings.TrimSpace(stringValue(value))
	if text == "" {
		return ""
	}
	text = htmlTagRE.ReplaceAllString(text, " ")
	return strings.TrimSpace(spaceRE.ReplaceAllString(text, " "))
}

func normalizeQuestionNumber(raw any, fallback int) int {
	match := digitRE.FindString(stringValue(raw))
	if match != "" {
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

func inferTypeCode(questionKind string, optionCount int, textInputs int) string {
	switch questionKind {
	case "multiple":
		return "4"
	case "dropdown":
		return "7"
	case "matrix":
		return "6"
	case "scale":
		return "5"
	case "order":
		return "11"
	case "single":
		return "3"
	case "text", "multi_text":
		return "1"
	}
	if textInputs > 0 {
		return "1"
	}
	if optionCount >= 2 {
		return "3"
	}
	return "1"
}

func resolveMatrixOptionTexts(raw map[string]any, optionTexts []string) []string {
	questionKind := strings.ToLower(strings.TrimSpace(stringValue(raw["question_kind"])))
	providerType := strings.ToLower(strings.TrimSpace(stringValue(raw["provider_type"])))
	if questionKind != "matrix" && providerType != "matrix" {
		return optionTexts
	}
	columnTexts := cleanTextList(stringList(raw["matrix_column_texts"]))
	if len(columnTexts) > 0 {
		return columnTexts
	}
	if len(optionTexts) > 0 {
		allGeneric := true
		for _, text := range optionTexts {
			if !genericMatrixOptionRE.MatchString(text) {
				allGeneric = false
				break
			}
		}
		if !allGeneric {
			return optionTexts
		}
	}
	return optionTexts
}

func isAnswerableQuestion(question model.QuestionMeta) bool {
	return question.Options > 0 || question.TextInputs > 0 || containsString([]string{"3", "4", "5", "6", "7", "11"}, question.TypeCode)
}
