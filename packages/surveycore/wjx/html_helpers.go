package wjx

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"

	nethtml "golang.org/x/net/html"
)

var forceSelectRE = regexp.MustCompile(`请(?:务必|一定|必须|直接)?\s*选(?:择)?\s*(?:第\s*(\d+)\s*(?:个|项|选项)?|([A-ZＡ-Ｚ])\s*(?:项|选项)?|(.+?))(?:[。；;，,、\s]|$)`)

func surveyTitle(root *nethtml.Node) string {
	for _, candidate := range findAll(root, func(node *nethtml.Node) bool {
		if !isElement(node, "div") && !isElement(node, "h1") && !isElement(node, "h2") {
			return false
		}
		id := strings.ToLower(attr(node, "id"))
		class := strings.ToLower(attr(node, "class"))
		return id == "divtitle" || id == "htitle" || id == "lbtitle" ||
			strings.Contains(class, "surveytitle") || strings.Contains(class, "survey-title") || strings.Contains(class, "wjx")
	}) {
		if text := cleanSurveyTitle(textContent(candidate)); text != "" {
			return text
		}
	}
	if title := findFirst(root, func(node *nethtml.Node) bool { return isElement(node, "title") }); title != nil {
		if text := cleanSurveyTitle(textContent(title)); text != "" {
			return text
		}
	}
	return "问卷星问卷"
}

func cleanSurveyTitle(value string) string {
	text := normalizeText(value)
	for _, suffix := range []string{"- 问卷星", "| 问卷星", "｜ 问卷星", "问卷星"} {
		text = strings.TrimSuffix(text, suffix)
	}
	return strings.TrimSpace(strings.Trim(text, "-_|｜ "))
}

func questionNumber(div *nethtml.Node) int {
	if number, err := strconv.Atoi(strings.TrimSpace(attr(div, "topic"))); err == nil && number > 0 {
		return number
	}
	if match := divNumberRE.FindStringSubmatch(attr(div, "id")); len(match) > 1 {
		number, _ := strconv.Atoi(match[1])
		if number > 0 {
			return number
		}
	}
	return 1
}

func questionTitle(div *nethtml.Node, fallback int) string {
	for _, match := range []func(*nethtml.Node) bool{
		func(node *nethtml.Node) bool { return classContains(node, "topichtml") },
		func(node *nethtml.Node) bool { return classContains(node, "field-label") },
		func(node *nethtml.Node) bool { return classContains(node, "qtypetip") },
		func(node *nethtml.Node) bool { return isElement(node, "blockquote") },
	} {
		node := findFirst(div, match)
		if node == nil {
			continue
		}
		if title := cleanupTitle(textContent(node)); title != "" {
			return title
		}
	}
	if title := cleanupTitle(textContent(div)); title != "" {
		return title
	}
	return fmt.Sprintf("第%d题", fallback)
}

func isHidden(node *nethtml.Node) bool {
	for current := node; current != nil; current = current.Parent {
		style := strings.ReplaceAll(strings.ToLower(attr(current, "style")), " ", "")
		if strings.Contains(style, "display:none") || strings.Contains(style, "visibility:hidden") {
			return true
		}
		if hidden := strings.ToLower(attr(current, "hidden")); hidden == "hidden" || hidden == "true" || hidden == "1" {
			return true
		}
		if classContains(current, "display-none") {
			return true
		}
	}
	return false
}

func required(div *nethtml.Node) bool {
	for _, key := range []string{"req", "required", "must", "wjxreq", "aria-required"} {
		value := strings.ToLower(strings.TrimSpace(attr(div, key)))
		if value == "1" || value == "true" || value == "required" {
			return true
		}
	}
	if findFirst(div, func(node *nethtml.Node) bool {
		return hasClass(node, "req") || hasClass(node, "required") || hasClass(node, "must") || hasClass(node, "wjxreq")
	}) != nil {
		return true
	}
	return strings.HasPrefix(normalizeText(textContent(div)), "*")
}

func looksLikeDescription(div *nethtml.Node, typeCode string) bool {
	relation := strings.TrimSpace(attr(div, "relation"))
	style := strings.ReplaceAll(strings.ToLower(attr(div, "style")), " ", "")
	if relation == "-1" && strings.Contains(style, "display:none") && !required(div) {
		return true
	}
	if typeCode != "3" && typeCode != "4" {
		return false
	}
	if containsInputType(div, map[string]bool{"radio": true, "checkbox": true}) {
		return false
	}
	if findFirst(div, func(node *nethtml.Node) bool {
		return classContains(node, "ui-controlgroup") || classContains(node, "jqradio") || classContains(node, "jqcheck")
	}) != nil {
		return false
	}
	return true
}

func looksLikeOrder(div *nethtml.Node) bool {
	if findFirst(div, func(node *nethtml.Node) bool {
		return classContains(node, "sortable") || classContains(node, "sortnum") || classContains(node, "order-number")
	}) != nil {
		return true
	}
	return false
}

func looksLikeRating(div *nethtml.Node) bool {
	if findFirst(div, func(node *nethtml.Node) bool {
		return classContains(node, "evaluateTagWrap") || classContains(node, "rate-off") || classContains(node, "rate-on") || classContains(node, "iconfontNew")
	}) == nil {
		return false
	}
	return !looksLikeNumericScale(div)
}

func looksLikeNumericScale(div *nethtml.Node) bool {
	anchors := findAll(div, func(node *nethtml.Node) bool {
		return isElement(node, "a") && (attr(node, "dval") != "" || attr(node, "val") != "" || attr(node, "data-value") != "")
	})
	if len(anchors) < 5 {
		return false
	}
	numeric := 0
	for _, anchor := range anchors {
		value := firstNonEmpty(attr(anchor, "dval"), attr(anchor, "val"), attr(anchor, "data-value"), textContent(anchor))
		if _, err := strconv.Atoi(strings.TrimSpace(value)); err == nil {
			numeric++
		}
	}
	return numeric >= maxInt(3, len(anchors)*7/10)
}

func looksLikeSliderMatrix(div *nethtml.Node) bool {
	inputs := findAll(div, func(node *nethtml.Node) bool {
		return isElement(node, "input") && classContains(node, "ui-slider-input") && attr(node, "rowid") != ""
	})
	if len(inputs) < 2 {
		return false
	}
	tracks := findAll(div, func(node *nethtml.Node) bool {
		return classContains(node, "rangeslider") || classContains(node, "range-slider") || classContains(node, "wjx-slider")
	})
	return len(tracks) >= len(inputs)
}

func isLocationQuestion(div *nethtml.Node) bool {
	if findFirst(div, func(node *nethtml.Node) bool { return classContains(node, "get_Local") }) != nil {
		return true
	}
	return findFirst(div, func(node *nethtml.Node) bool {
		if !isElement(node, "input") {
			return false
		}
		verify := attr(node, "verify")
		onclick := strings.ToLower(attr(node, "onclick"))
		return strings.Contains(verify, "地图") || strings.Contains(verify, "省市") || strings.Contains(verify, "省份") || strings.Contains(verify, "城市") || strings.Contains(verify, "地区") || strings.Contains(onclick, "opencitybox")
	}) != nil
}

func countTextInputs(div *nethtml.Node) int {
	return len(findAll(div, isTextInputNode))
}

func providerType(typeCode string, textInputs int, optionCount int, sliderMatrix bool) string {
	if sliderMatrix {
		return "matrix"
	}
	switch typeCode {
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
		if textInputs > 1 {
			return "multi_text"
		}
		if textInputs > 0 || optionCount == 0 {
			return "text"
		}
		return "text"
	}
}

func isTextLike(typeCode string, textInputs int, optionCount int, isLocation bool) bool {
	if isLocation {
		return false
	}
	switch typeCode {
	case "3", "4", "5", "6", "7", "8", "11":
		return false
	}
	return typeCode == "1" || typeCode == "2" || typeCode == "9" || textInputs > 0 || optionCount == 0
}

func ratingMax(isRating bool, optionCount int) int {
	if !isRating {
		return 0
	}
	return optionCount
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if text := normalizeText(value); text != "" {
			return text
		}
	}
	return ""
}

func optionLabel(text string) string {
	trimmed := strings.TrimSpace(text)
	if strings.HasPrefix(trimmed, "(") && len(trimmed) >= 3 {
		return strings.ToUpper(strings.TrimSpace(trimmed[1:2]))
	}
	if strings.HasPrefix(trimmed, "（") && len([]rune(trimmed)) >= 3 {
		runes := []rune(trimmed)
		return strings.ToUpper(string(runes[1]))
	}
	return ""
}

func forceSelectOption(title string, optionTexts []string) (*int, string) {
	if len(optionTexts) == 0 {
		return nil, ""
	}
	match := forceSelectRE.FindStringSubmatch(title)
	if len(match) == 0 {
		return nil, ""
	}
	if match[1] != "" {
		number, _ := strconv.Atoi(match[1])
		index := number - 1
		if index >= 0 && index < len(optionTexts) {
			return &index, optionTexts[index]
		}
	}
	if match[2] != "" {
		label := strings.ToUpper(strings.TrimSpace(match[2]))
		for index, text := range optionTexts {
			if optionLabel(text) == label {
				idx := index
				return &idx, text
			}
		}
	}
	target := normalizeText(match[3])
	if target != "" {
		for index, text := range optionTexts {
			if strings.Contains(target, normalizeText(text)) || strings.Contains(title, normalizeText(text)) {
				idx := index
				return &idx, text
			}
		}
	}
	return nil, ""
}
