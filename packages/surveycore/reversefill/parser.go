package reversefill

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"surveycontroller/surveycore"
)

var (
	leadingIndexRE = regexp.MustCompile(`^[\(\[（【]?\s*(\d+)\s*[\)\]）】、.．]?\s*`)
	numberTextRE   = regexp.MustCompile(`^\d+(?:\.0+)?$`)
)

func SupportsRuntime(questionType string, info surveycore.QuestionMeta) bool {
	normalized := strings.ToLower(strings.TrimSpace(questionType))
	switch normalized {
	case "single", "dropdown", "scale", "score", "text", "multi_text", "matrix":
	default:
		return false
	}
	if normalized == "text" && info.IsTextLike && info.ProviderType == "location" {
		return false
	}
	if normalized == "single" || normalized == "dropdown" {
		if len(info.FillableOptions) > 0 {
			return false
		}
	}
	return true
}

func ResolveOrderedColumns(columns []Column, expectedLabels []string) []Column {
	ordered := append([]Column(nil), columns...)
	sort.SliceStable(ordered, func(i, j int) bool { return ordered[i].ColumnIndex < ordered[j].ColumnIndex })
	if len(ordered) == 0 || len(expectedLabels) == 0 || len(ordered) != len(expectedLabels) {
		return ordered
	}
	labelIndex := map[string]int{}
	for index, label := range expectedLabels {
		for _, variant := range labelVariants(label) {
			if _, exists := labelIndex[variant]; !exists {
				labelIndex[variant] = index
			}
		}
	}
	resolved := make([]Column, len(expectedLabels))
	used := map[int]bool{}
	for _, column := range ordered {
		found := false
		for _, variant := range labelVariants(column.Suffix) {
			target, ok := labelIndex[variant]
			if !ok || used[target] {
				continue
			}
			resolved[target] = column
			used[target] = true
			found = true
			break
		}
		if !found {
			return ordered
		}
	}
	if len(used) != len(expectedLabels) {
		return ordered
	}
	return resolved
}

func ParseChoiceAnswer(questionNum int, rawValue string, exportFormat string, optionTexts []string) (*Answer, error) {
	if isBlank(rawValue) {
		return nil, nil
	}
	text := normalizeText(rawValue)
	if strings.Contains(text, "┋") {
		return nil, fmt.Errorf("检测到多选串，V1 不支持")
	}
	if strings.Contains(text, "→") {
		return nil, fmt.Errorf("检测到排序串，V1 不支持")
	}
	if strings.Contains(text, "〖") && strings.Contains(text, "〗") {
		return nil, fmt.Errorf("检测到选项附加填空复合值，V1 不支持")
	}
	if exportFormat == FormatWJXSequence {
		return answerByOneBasedIndex(questionNum, text, optionTexts)
	}
	optionMap := optionTextIndexMap(optionTexts)
	for _, variant := range labelVariants(text) {
		if index, ok := optionMap[variant]; ok {
			return choiceAnswer(questionNum, index), nil
		}
	}
	if exportFormat == FormatWJXScore || exportFormat == FormatWJXText || exportFormat == FormatAuto {
		if answer, err := answerByOneBasedIndex(questionNum, text, optionTexts); err == nil {
			return answer, nil
		}
	}
	return nil, fmt.Errorf("无法把值“%s”匹配到题目选项", text)
}

func ParseTextAnswer(questionNum int, rawValue string) *Answer {
	if isBlank(rawValue) {
		return nil
	}
	return &Answer{QuestionNum: questionNum, Kind: KindText, TextValue: normalizeText(rawValue)}
}

func ParseMultiTextAnswer(questionNum int, columns []Column, row RawRow) *Answer {
	values := make([]string, 0, len(columns))
	hasValue := false
	for _, column := range columns {
		text := normalizeText(row.ValuesByColumn[column.ColumnIndex])
		if text != "" {
			hasValue = true
		}
		values = append(values, text)
	}
	if !hasValue {
		return nil
	}
	return &Answer{QuestionNum: questionNum, Kind: KindMultiText, TextValues: values}
}

func ParseMatrixAnswer(questionNum int, columns []Column, row RawRow, exportFormat string, optionTexts []string) (*Answer, error) {
	values := make([]string, 0, len(columns))
	for _, column := range columns {
		values = append(values, row.ValuesByColumn[column.ColumnIndex])
	}
	blankCount := 0
	for _, value := range values {
		if isBlank(value) {
			blankCount++
		}
	}
	if blankCount == len(values) {
		return nil, nil
	}
	if blankCount > 0 {
		return nil, fmt.Errorf("矩阵题存在部分行为空，V1 不能可靠回放")
	}
	indexes := make([]int, 0, len(values))
	for _, value := range values {
		answer, err := ParseChoiceAnswer(questionNum, value, exportFormat, optionTexts)
		if err != nil {
			return nil, err
		}
		if answer == nil || answer.ChoiceIndex == nil {
			return nil, fmt.Errorf("矩阵题行值解析失败")
		}
		indexes = append(indexes, *answer.ChoiceIndex)
	}
	return &Answer{QuestionNum: questionNum, Kind: KindMatrix, MatrixChoiceIndexes: indexes}, nil
}

func InferQuestionColumns(headers []string) map[int][]Column {
	result := map[int][]Column{}
	for index, header := range headers {
		questionNum, suffix, ok := parseHeader(header)
		if !ok {
			continue
		}
		result[questionNum] = append(result[questionNum], Column{
			ColumnIndex: index + 1,
			Header:      header,
			QuestionNum: questionNum,
			Suffix:      suffix,
		})
	}
	return result
}

func parseHeader(header string) (int, string, bool) {
	text := normalizeText(header)
	match := leadingIndexRE.FindStringSubmatch(text)
	if len(match) < 2 {
		return 0, "", false
	}
	num, err := strconv.Atoi(match[1])
	if err != nil || num <= 0 {
		return 0, "", false
	}
	suffix := strings.TrimSpace(text[len(match[0]):])
	for _, sep := range []string{"-", "—", "–", ":", "：", "|", "｜", "/"} {
		if strings.Contains(suffix, sep) {
			parts := strings.Split(suffix, sep)
			suffix = strings.TrimSpace(parts[len(parts)-1])
		}
	}
	return num, suffix, true
}

func answerByOneBasedIndex(questionNum int, text string, optionTexts []string) (*Answer, error) {
	if !numberTextRE.MatchString(text) {
		return nil, fmt.Errorf("无法把值“%s”解析为序号", text)
	}
	oneBased, err := strconv.Atoi(strings.TrimSuffix(text, ".0"))
	if err != nil || oneBased <= 0 {
		return nil, fmt.Errorf("无法把值“%s”解析为序号", text)
	}
	zeroBased := oneBased - 1
	if zeroBased < 0 || zeroBased >= len(optionTexts) {
		return nil, fmt.Errorf("序号 %d 超出选项范围", oneBased)
	}
	return choiceAnswer(questionNum, zeroBased), nil
}

func choiceAnswer(questionNum int, index int) *Answer {
	value := index
	return &Answer{QuestionNum: questionNum, Kind: KindChoice, ChoiceIndex: &value}
}

func optionTextIndexMap(optionTexts []string) map[string]int {
	result := map[string]int{}
	for index, text := range optionTexts {
		for _, variant := range labelVariants(text) {
			if _, exists := result[variant]; !exists {
				result[variant] = index
			}
		}
	}
	return result
}

func labelVariants(value string) []string {
	text := normalizeText(value)
	if text == "" {
		return nil
	}
	var result []string
	add := func(candidate string) {
		key := normalizeKey(candidate)
		if key == "" {
			return
		}
		for _, existing := range result {
			if existing == key {
				return
			}
		}
		result = append(result, key)
	}
	add(text)
	stripped := leadingIndexRE.ReplaceAllString(text, "")
	add(strings.Trim(stripped, " _"))
	for _, sep := range []string{"-", ":", "丨", "|", "/", "／", "—", "–", "－"} {
		if strings.Contains(stripped, sep) {
			parts := strings.Split(stripped, sep)
			add(strings.Trim(parts[len(parts)-1], " _"))
		}
	}
	return result
}

func normalizeKey(value string) string {
	text := normalizeText(value)
	text = strings.NewReplacer("（", "(", "）", ")", "【", "[", "】", "]", "—", "-", "–", "-", "－", "-", "：", ":").Replace(text)
	text = strings.Join(strings.Fields(text), "")
	return strings.ToLower(text)
}

func normalizeText(value string) string {
	if value == "" {
		return ""
	}
	return strings.TrimSpace(value)
}

func isBlank(value string) bool {
	return normalizeText(value) == ""
}
