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
	forceSelectCommandRE  = regexp.MustCompile(`请(?:务必|一定|必须|直接)?\s*选(?:择)?\s*(?:第?\s*(\d{1,3})\s*(?:个|项|选项)?|([A-Za-z])(?:项|选项)?|([^，,。；;！!？?\s]+))`)
	forceTextRE           = regexp.MustCompile(`请(?:务必|一定|必须|直接)?\s*(?:输入|填写|填入|写入)\s*[：:\s]*["“'‘]?([^"”'’\s，,。；;！!？?）)]+)`)
	arithmeticRE          = regexp.MustCompile(`(?:^|[^\d.])(\d+(?:\.\d+)?)\s*([+\-*/×xX÷])\s*(\d+(?:\.\d+)?)(?:$|[^\d.])`)
	numberRE              = regexp.MustCompile(`-?\d+(?:\.\d+)?`)
	multiLimitRE          = regexp.MustCompile(`(至少|最少|不少于|至多|最多|不超过)\s*(?:可)?(?:选择|选)?\s*(\d{1,3})\s*(?:个)?(?:选项|项)?`)
	multiRangeRE          = regexp.MustCompile(`(?:选择|选)\s*(\d{1,3})\s*(?:-|~|～|至|到)\s*(\d{1,3})\s*(?:个)?(?:选项|项)`)
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
	extraFragments := []any{raw["title_text"], raw["tip_text"]}
	forcedIdx, forcedOption := forcedOption(rawTitle, optionTexts, extraFragments)
	if forcedIdx == nil {
		forcedIdx, forcedOption = arithmeticOption(rawTitle, optionTexts, extraFragments)
	}
	forcedTexts := forcedTexts(rawTitle, extraFragments)
	multiMin, multiMax := multiLimitsFromText(rawTitle, len(optionTexts), extraFragments)

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
		ForcedOptionIdx: forcedIdx,
		ForcedOption:    forcedOption,
		ForcedTexts:     forcedTexts,
		FillableOptions: intList(raw["fillable_options"]),
		MultiMinLimit:   multiMin,
		MultiMaxLimit:   multiMax,
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

func forcedOption(title string, optionTexts []string, extra []any) (*int, string) {
	fragments := fragments(title, extra)
	for _, fragment := range fragments {
		match := forceSelectCommandRE.FindStringSubmatch(fragment)
		if len(match) == 0 {
			continue
		}
		if match[1] != "" {
			index, _ := strconv.Atoi(match[1])
			index--
			if index >= 0 && index < len(optionTexts) {
				return &index, optionTexts[index]
			}
		}
		target := normalizeText(firstAny(match[2], match[3]))
		if target == "" {
			continue
		}
		for index, option := range optionTexts {
			if strings.EqualFold(optionLabel(option), target) || strings.Contains(normalizeText(option), target) || strings.Contains(target, normalizeText(option)) {
				idx := index
				return &idx, option
			}
		}
	}
	return nil, ""
}

func arithmeticOption(title string, optionTexts []string, extra []any) (*int, string) {
	for _, fragment := range fragments(title, extra) {
		match := arithmeticRE.FindStringSubmatch(fragment)
		if len(match) < 4 {
			continue
		}
		result, ok := evalSimple(match[1], match[2], match[3])
		if !ok {
			continue
		}
		for index, option := range optionTexts {
			if value, ok := firstNumber(option); ok && value == result {
				idx := index
				return &idx, option
			}
		}
	}
	return nil, ""
}

func forcedTexts(title string, extra []any) []string {
	result := make([]string, 0)
	seen := map[string]bool{}
	for _, fragment := range fragments(title, extra) {
		for _, match := range forceTextRE.FindAllStringSubmatch(fragment, -1) {
			if len(match) < 2 {
				continue
			}
			text := normalizeText(match[1])
			if text != "" && !seen[text] {
				seen[text] = true
				result = append(result, text)
			}
		}
	}
	return result
}

func multiLimitsFromText(title string, optionCount int, extra []any) (*int, *int) {
	var minPtr *int
	var maxPtr *int
	for _, fragment := range fragments(title, extra) {
		for _, match := range multiLimitRE.FindAllStringSubmatch(fragment, -1) {
			if len(match) < 3 {
				continue
			}
			value, _ := strconv.Atoi(match[2])
			if optionCount > 0 && value > optionCount {
				value = optionCount
			}
			switch match[1] {
			case "至少", "最少", "不少于":
				minPtr = mergeMin(minPtr, value)
			default:
				maxPtr = mergeMax(maxPtr, value)
			}
		}
		if match := multiRangeRE.FindStringSubmatch(fragment); len(match) >= 3 {
			minValue, _ := strconv.Atoi(match[1])
			maxValue, _ := strconv.Atoi(match[2])
			if minValue > maxValue {
				minValue, maxValue = maxValue, minValue
			}
			minPtr = mergeMin(minPtr, minValue)
			maxPtr = mergeMax(maxPtr, maxValue)
		}
	}
	if minPtr != nil && maxPtr != nil && *minPtr > *maxPtr {
		*minPtr = *maxPtr
	}
	return minPtr, maxPtr
}

func fragments(title string, extra []any) []string {
	result := make([]string, 0, len(extra)+1)
	seen := map[string]bool{}
	for _, item := range append([]any{title}, extra...) {
		text := normalizeText(item)
		if text != "" && !seen[text] {
			seen[text] = true
			result = append(result, text)
		}
	}
	return result
}

func optionLabel(text string) string {
	trimmed := strings.TrimSpace(text)
	if strings.HasPrefix(trimmed, "(") && len(trimmed) >= 2 {
		return strings.ToUpper(trimmed[1:2])
	}
	return ""
}

func evalSimple(left string, op string, right string) (float64, bool) {
	l, err := strconv.ParseFloat(strings.TrimSpace(left), 64)
	if err != nil {
		return 0, false
	}
	r, err := strconv.ParseFloat(strings.TrimSpace(right), 64)
	if err != nil {
		return 0, false
	}
	switch op {
	case "+":
		return l + r, true
	case "-":
		return l - r, true
	case "*", "×", "x", "X":
		return l * r, true
	case "/", "÷":
		if r == 0 {
			return 0, false
		}
		return l / r, true
	default:
		return 0, false
	}
}

func firstNumber(text string) (float64, bool) {
	match := numberRE.FindString(text)
	if match == "" {
		return 0, false
	}
	value, err := strconv.ParseFloat(match, 64)
	return value, err == nil
}

func mergeMin(current *int, value int) *int {
	if value <= 0 {
		return current
	}
	if current == nil || value > *current {
		next := value
		return &next
	}
	return current
}

func mergeMax(current *int, value int) *int {
	if value <= 0 {
		return current
	}
	if current == nil || value < *current {
		next := value
		return &next
	}
	return current
}
