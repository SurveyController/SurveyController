package answerplan

import (
	"fmt"
	"math/rand"
	"strconv"
	"strings"
	"time"

	"surveycontroller/surveycore/internal/model"
)

const (
	defaultFillText      = "无"
	multiTextDelimiter   = "||"
	randomNameToken      = "__RANDOM_NAME__"
	randomMobileToken    = "__RANDOM_MOBILE__"
	randomIDCardToken    = "__RANDOM_ID_CARD__"
	randomGenericText    = "__RANDOM_TEXT__"
	randomIntTokenPrefix = "__RANDOM_INT__:"
	textRandomNone       = "none"
	textRandomName       = "name"
	textRandomMobile     = "mobile"
	textRandomIDCard     = "id_card"
	textRandomInteger    = "integer"
	idCardChecksumChars  = "10X98765432"
	defaultSliderValue   = "50"
)

var idCardChecksumWeights = []int{7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2}

func ResolveTextValues(entry model.QuestionEntry, question model.QuestionMeta, blankCount int) []string {
	return ResolveTextValuesWithPersona(entry, question, blankCount, nil)
}

func ResolveTextValuesWithPersona(entry model.QuestionEntry, question model.QuestionMeta, blankCount int, persona *model.Persona) []string {
	count := maxInt(1, blankCount)
	candidates := normalizedTexts(entry.Texts)
	if len(candidates) == 0 {
		candidates = normalizedTexts(question.ForcedTexts)
	}
	if len(candidates) == 0 {
		candidates = []string{defaultFillText}
	}
	selected := candidates[SelectedTextIndex(candidates, entry.Probabilities)]
	values := []string{resolveDynamicTextTokenWithPersona(selected, persona)}
	if normalizeTextRandomMode(entry.TextRandomMode) == textRandomNone && strings.Contains(selected, multiTextDelimiter) {
		values = values[:0]
		for _, part := range strings.Split(selected, multiTextDelimiter) {
			values = append(values, resolveDynamicTextTokenWithPersona(part, persona))
		}
	}
	if mode := normalizeTextRandomMode(entry.TextRandomMode); mode != textRandomNone {
		values = []string{randomValueForMode(mode, entry.TextRandomIntRange, persona)}
	}
	if len(values) == 0 {
		values = []string{defaultFillText}
	}
	for len(values) < count {
		values = append(values, values[len(values)-1])
	}
	values = values[:count]
	for index := range values {
		mode := textRandomNone
		if index < len(entry.MultiTextBlankModes) {
			mode = normalizeTextRandomMode(entry.MultiTextBlankModes[index])
		}
		if mode != textRandomNone {
			var intRange []int
			if index < len(entry.MultiTextBlankIntRanges) {
				intRange = entry.MultiTextBlankIntRanges[index]
			}
			values[index] = randomValueForMode(mode, intRange, persona)
		}
		values[index] = firstNonEmpty(values[index], defaultFillText)
	}
	return values
}

func normalizedTexts(values []string) []string {
	result := make([]string, 0, len(values))
	for _, value := range values {
		if text := strings.TrimSpace(value); text != "" {
			result = append(result, text)
		}
	}
	return result
}

func normalizeTextRandomMode(value string) string {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case textRandomName:
		return textRandomName
	case textRandomMobile:
		return textRandomMobile
	case textRandomIDCard:
		return textRandomIDCard
	case textRandomInteger:
		return textRandomInteger
	default:
		return textRandomNone
	}
}

func randomValueForMode(mode string, intRange []int, persona *model.Persona) string {
	switch normalizeTextRandomMode(mode) {
	case textRandomName:
		return randomChineseName(persona)
	case textRandomMobile:
		return randomMobile()
	case textRandomIDCard:
		return randomIDCard(persona)
	case textRandomInteger:
		return randomIntegerText(intRange)
	default:
		return defaultFillText
	}
}

func resolveDynamicTextToken(value string) string {
	return resolveDynamicTextTokenWithPersona(value, nil)
}

func resolveDynamicTextTokenWithPersona(value string, persona *model.Persona) string {
	text := strings.TrimSpace(value)
	switch text {
	case "":
		return defaultFillText
	case randomNameToken:
		return randomChineseName(persona)
	case randomMobileToken:
		return randomMobile()
	case randomIDCardToken:
		return randomIDCard(persona)
	case randomGenericText:
		return randomGeneric()
	}
	if minValue, maxValue, ok := parseRandomIntToken(text); ok {
		return strconv.Itoa(randomIntInRange(minValue, maxValue))
	}
	return text
}

func parseRandomIntToken(token string) (int, int, bool) {
	if !strings.HasPrefix(token, randomIntTokenPrefix) {
		return 0, 0, false
	}
	payload := strings.TrimPrefix(token, randomIntTokenPrefix)
	parts := strings.SplitN(payload, ":", 2)
	if len(parts) != 2 {
		return 0, 0, false
	}
	minValue, errMin := strconv.Atoi(strings.TrimSpace(parts[0]))
	maxValue, errMax := strconv.Atoi(strings.TrimSpace(parts[1]))
	if errMin != nil || errMax != nil {
		return 0, 0, false
	}
	if minValue > maxValue {
		minValue, maxValue = maxValue, minValue
	}
	return minValue, maxValue, true
}

func randomIntegerText(intRange []int) string {
	if len(intRange) < 2 {
		return defaultFillText
	}
	return strconv.Itoa(randomIntInRange(intRange[0], intRange[1]))
}

func randomIntInRange(minValue int, maxValue int) int {
	if minValue > maxValue {
		minValue, maxValue = maxValue, minValue
	}
	if minValue == maxValue {
		return minValue
	}
	return minValue + rand.Intn(maxValue-minValue+1)
}

func randomChineseName(persona *model.Persona) string {
	surnames := []rune("张王李赵陈杨刘黄周吴徐孙马朱胡林郭何高罗郑梁谢宋唐韩曹许邓冯")
	maleGivenPool := []rune("伟俊涛强磊刚凯鹏鑫宇浩瑞博杰宁豪轩皓浩宇子豪思远家豪文博宇航志强明浩志伟文涛梓豪志鹏伟豪君豪承泽")
	femaleGivenPool := []rune("婷雅静怡欣萱琳玲芳颖慧敏雪晶莉倩蕾佳媛茜悦岚蓉瑶诗梦菲琪韵彤璐")
	neutralGivenPool := []rune("嘉明华建安晨泽文超洋")
	givenPool := append(append([]rune(nil), maleGivenPool...), femaleGivenPool...)
	givenPool = append(givenPool, neutralGivenPool...)
	if persona != nil {
		switch persona.Gender {
		case "男":
			givenPool = append(append([]rune(nil), maleGivenPool...), neutralGivenPool...)
		case "女":
			givenPool = append(append([]rune(nil), femaleGivenPool...), neutralGivenPool...)
		}
	}
	surname := string(surnames[rand.Intn(len(surnames))])
	givenLen := 1
	if rand.Float64() >= 0.65 {
		givenLen = 2
	}
	var builder strings.Builder
	builder.WriteString(surname)
	for index := 0; index < givenLen; index++ {
		builder.WriteRune(givenPool[rand.Intn(len(givenPool))])
	}
	return builder.String()
}

func randomMobile() string {
	prefixes := []string{
		"130", "131", "132", "133", "134", "135", "136", "137", "138", "139",
		"147", "150", "151", "152", "153", "155", "156", "157", "158", "159",
		"166", "171", "172", "173", "175", "176", "177", "178", "180", "181",
		"182", "183", "184", "185", "186", "187", "188", "189", "198", "199",
	}
	var builder strings.Builder
	builder.WriteString(prefixes[rand.Intn(len(prefixes))])
	for index := 0; index < 8; index++ {
		builder.WriteByte(byte('0' + rand.Intn(10)))
	}
	return builder.String()
}

func randomIDCard(persona *model.Persona) string {
	areaCodes := []string{"110100", "310100", "440100", "330100", "510100"}
	minAge, maxAge := personaAgeRange(persona)
	age := randomIntInRange(minAge, maxAge)
	year := time.Now().Year() - age
	start := time.Date(year, 1, 1, 0, 0, 0, 0, time.Local)
	birthday := start.AddDate(0, 0, rand.Intn(365))
	prefix := fmt.Sprintf("%s%s%02d%d", areaCodes[rand.Intn(len(areaCodes))], birthday.Format("20060102"), rand.Intn(100), personaGenderDigit(persona))
	return prefix + string(idCardChecksum(prefix))
}

func personaAgeRange(persona *model.Persona) (int, int) {
	if persona == nil {
		return 18, 60
	}
	switch persona.AgeGroup {
	case "18-25":
		return 18, 25
	case "26-35":
		return 26, 35
	case "36-45":
		return 36, 45
	case "46-60":
		return 46, 60
	default:
		return 18, 60
	}
}

func personaGenderDigit(persona *model.Persona) int {
	if persona != nil {
		switch persona.Gender {
		case "男":
			return []int{1, 3, 5, 7, 9}[rand.Intn(5)]
		case "女":
			return []int{0, 2, 4, 6, 8}[rand.Intn(5)]
		}
	}
	return rand.Intn(10)
}

func idCardChecksum(firstSeventeen string) byte {
	if len(firstSeventeen) != 17 {
		return '0'
	}
	total := 0
	for index, char := range firstSeventeen {
		if char < '0' || char > '9' || index >= len(idCardChecksumWeights) {
			return '0'
		}
		total += int(char-'0') * idCardChecksumWeights[index]
	}
	return idCardChecksumChars[total%11]
}

func randomGeneric() string {
	samples := []string{"已填写", "同上", "无", "OK", "收到", "确认", "正常", "通过", "测试数据", "自动填写"}
	return samples[rand.Intn(len(samples))] + strconv.Itoa(randomIntInRange(10, 999))
}
