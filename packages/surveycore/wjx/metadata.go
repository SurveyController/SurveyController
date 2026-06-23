package wjx

import (
	"strconv"
	"strings"

	nethtml "golang.org/x/net/html"
)

func textInputLabels(div *nethtml.Node) []string {
	inputs := findAll(div, isTextInputNode)
	if len(inputs) <= 1 {
		return nil
	}
	labels := make([]string, 0, len(inputs))
	for index, input := range inputs {
		label := firstNonEmpty(attr(input, "placeholder"), attr(input, "aria-label"), attr(input, "name"), attr(input, "id"))
		if label == "" && input.Parent != nil && input.Parent != div {
			label = normalizeText(textContent(input.Parent))
		}
		if label == "" {
			label = "填空" + strconv.Itoa(index+1)
		}
		labels = append(labels, label)
	}
	return labels
}

func attachedOptionSelects(div *nethtml.Node, optionTexts []string) []map[string]any {
	selects := findAll(div, func(node *nethtml.Node) bool {
		return isElement(node, "select")
	})
	result := make([]map[string]any, 0)
	seen := map[int]bool{}
	for _, selectNode := range selects {
		optionNode := selectNode.Parent
		for optionNode != nil && optionNode != div && !(isElement(optionNode, "div") || isElement(optionNode, "li")) {
			optionNode = optionNode.Parent
		}
		index := -1
		if optionNode != nil && optionNode != div {
			index = optionIndexForNode(optionNode, optionTexts)
		}
		if index < 0 || seen[index] {
			continue
		}
		seen[index] = true
		choices := selectOptionTexts(selectNode)
		if len(choices) == 0 {
			continue
		}
		result = append(result, map[string]any{
			"option_index": index,
			"option_text":  optionTexts[index],
			"select_texts": choices,
		})
	}
	return result
}

func selectOptionTexts(selectNode *nethtml.Node) []string {
	options := findAll(selectNode, func(node *nethtml.Node) bool { return isElement(node, "option") })
	texts := make([]string, 0, len(options))
	for _, option := range options {
		text := normalizeText(textContent(option))
		if text == "" || strings.HasPrefix(strings.ReplaceAll(text, " ", ""), "请选择") {
			continue
		}
		texts = append(texts, text)
	}
	return dedupeTexts(texts)
}

func questionMedia(div *nethtml.Node, rowTexts []string, optionTexts []string) []map[string]any {
	media := make([]map[string]any, 0)
	for _, image := range findAll(div, func(node *nethtml.Node) bool { return isElement(node, "img") }) {
		source := firstNonEmpty(attr(image, "src"), attr(image, "data-src"), attr(image, "data-original"))
		if source == "" {
			continue
		}
		scope, index, label := "title", any(nil), "题干图"
		for parent := image.Parent; parent != nil && parent != div; parent = parent.Parent {
			if rowIndex := rowIndexForNode(parent, rowTexts); rowIndex >= 0 {
				scope, index, label = "row", rowIndex, rowTexts[rowIndex]
				break
			}
			if optionIndex := optionIndexForNode(parent, optionTexts); optionIndex >= 0 {
				scope, index, label = "option", optionIndex, optionTexts[optionIndex]
				break
			}
		}
		media = append(media, map[string]any{
			"kind":       "image",
			"scope":      scope,
			"index":      index,
			"source_url": normalizeMediaURL(source),
			"label":      label,
		})
	}
	return media
}

func rowIndexForNode(node *nethtml.Node, rowTexts []string) int {
	text := normalizeText(textContent(node))
	for index, row := range rowTexts {
		if row != "" && strings.Contains(text, row) {
			return index
		}
	}
	return -1
}

func optionIndexForNode(node *nethtml.Node, optionTexts []string) int {
	text := normalizeText(textContent(node))
	for index, option := range optionTexts {
		if option != "" && strings.Contains(text, option) {
			return index
		}
	}
	return -1
}

func normalizeMediaURL(raw string) string {
	text := strings.TrimSpace(raw)
	if strings.HasPrefix(text, "//") {
		return "https:" + text
	}
	return text
}

func sliderRange(div *nethtml.Node) (any, any, any) {
	input := findFirst(div, func(node *nethtml.Node) bool {
		return isElement(node, "input") && (attr(node, "type") == "range" || classContains(node, "ui-slider-input"))
	})
	if input == nil {
		return nil, nil, nil
	}
	return firstNonEmpty(attr(input, "min"), "0"), firstNonEmpty(attr(input, "max"), "100"), firstNonEmpty(attr(input, "step"), "1")
}

func logicMetadata(div *nethtml.Node, questionNum int, optionTexts []string) (bool, []map[string]any, bool, []map[string]any, bool, []map[string]any, string) {
	jumpRules := make([]map[string]any, 0)
	for _, node := range findAll(div, func(node *nethtml.Node) bool {
		return attr(node, "jumpto") != "" || attr(node, "jump") != "" || attr(node, "data-jumpto") != ""
	}) {
		target := intValue(firstNonEmpty(attr(node, "jumpto"), attr(node, "jump"), attr(node, "data-jumpto")))
		if target <= 0 {
			continue
		}
		optionIndex := optionIndexForNode(node, optionTexts)
		jumpRules = append(jumpRules, map[string]any{
			"option_index": optionIndex,
			"jumpto":       target,
			"option_text":  optionTextAt(optionTexts, optionIndex),
		})
	}
	hasDisplay := isHidden(div) || strings.TrimSpace(attr(div, "relation")) != ""
	displayConditions := make([]map[string]any, 0)
	if relation := strings.TrimSpace(attr(div, "relation")); relation != "" && relation != "-1" {
		displayConditions = append(displayConditions, map[string]any{
			"condition_question_num":   intValue(relation),
			"condition_mode":           "selected",
			"condition_option_indices": []int{},
		})
	}
	hasLogic := len(jumpRules) > 0 || hasDisplay
	status := "none"
	if hasLogic {
		status = "complete"
	}
	_ = questionNum
	return len(jumpRules) > 0, jumpRules, hasDisplay, displayConditions, false, nil, status
}

func optionTextAt(values []string, index int) any {
	if index < 0 || index >= len(values) {
		return nil
	}
	return values[index]
}
