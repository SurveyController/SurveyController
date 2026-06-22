package wjx

import (
	"sort"
	"strconv"
	"strings"

	nethtml "golang.org/x/net/html"
)

func questionOptions(div *nethtml.Node, questionNum int, typeCode string) ([]string, []string, []int) {
	switch typeCode {
	case "3", "4", "5", "11":
		options, fillable := choiceTexts(div)
		return options, nil, fillable
	case "7":
		options := selectTexts(div)
		fillable := []int{}
		if len(options) > 0 && containsTextInput(div) {
			fillable = append(fillable, len(options)-1)
		}
		return options, nil, fillable
	case "6":
		options, rows := matrixTexts(div, questionNum)
		return options, rows, nil
	case "8":
		return []string{"50"}, nil, nil
	default:
		if looksLikeSliderMatrix(div) {
			options, rows := sliderMatrixTexts(div)
			return options, rows, nil
		}
		return nil, nil, nil
	}
}

func choiceTexts(div *nethtml.Node) ([]string, []int) {
	var optionNodes []*nethtml.Node
	group := findFirst(div, func(node *nethtml.Node) bool { return classContains(node, "ui-controlgroup") })
	if group != nil {
		optionNodes = directElementChildren(group)
	}
	if len(optionNodes) == 0 {
		optionNodes = findAll(div, func(node *nethtml.Node) bool { return isElement(node, "li") })
	}
	texts := make([]string, 0, len(optionNodes))
	fillable := make([]int, 0)
	for _, option := range optionNodes {
		labelNode := findFirst(option, func(node *nethtml.Node) bool { return hasClass(node, "label") })
		text := textContent(option)
		if labelNode != nil {
			text = textContent(labelNode)
		}
		text = normalizeText(text)
		if text == "" {
			text = firstNonEmpty(attr(option, "title"), attr(option, "data-title"), attr(option, "aria-label"), attr(option, "value"))
		}
		if text == "" {
			continue
		}
		index := len(texts)
		texts = append(texts, text)
		if containsTextInput(option) {
			fillable = append(fillable, index)
		}
	}
	if len(fillable) == 0 && len(texts) > 0 {
		other := findFirst(div, func(node *nethtml.Node) bool { return classContains(node, "ui-other") && containsTextInput(node) })
		if other != nil {
			fillable = append(fillable, len(texts)-1)
		}
	}
	return dedupeTexts(texts), fillable
}

func ratingTexts(div *nethtml.Node) []string {
	anchors := findAll(div, func(node *nethtml.Node) bool {
		return isElement(node, "a") && (classContains(node, "rate-") || attr(node, "val") != "" || attr(node, "dval") != "")
	})
	texts := make([]string, 0, len(anchors))
	for index, anchor := range anchors {
		text := firstNonEmpty(attr(anchor, "title"), attr(anchor, "aria-label"), attr(anchor, "val"), attr(anchor, "dval"), attr(anchor, "data-value"), textContent(anchor))
		if text == "" {
			text = strconv.Itoa(index + 1)
		}
		texts = append(texts, text)
	}
	return dedupeTexts(texts)
}

func selectTexts(div *nethtml.Node) []string {
	selectNode := findFirst(div, func(node *nethtml.Node) bool { return isElement(node, "select") })
	if selectNode == nil {
		return nil
	}
	options := findAll(selectNode, func(node *nethtml.Node) bool { return isElement(node, "option") })
	texts := make([]string, 0, len(options))
	for index, option := range options {
		value := strings.TrimSpace(attr(option, "value"))
		text := normalizeText(textContent(option))
		if index == 0 && (value == "" || value == "0" || value == "-1" || strings.HasPrefix(strings.ReplaceAll(text, " ", ""), "请选择")) {
			continue
		}
		if text != "" {
			texts = append(texts, text)
		}
	}
	return dedupeTexts(texts)
}

func matrixTexts(div *nethtml.Node, questionNum int) ([]string, []string) {
	table := findFirst(div, func(node *nethtml.Node) bool {
		return isElement(node, "table") && (attr(node, "id") == "divRefTab"+strconv.Itoa(questionNum) || strings.HasPrefix(attr(node, "id"), "divRefTab"))
	})
	if table == nil {
		return matrixTextsFromInputNames(div, questionNum)
	}
	rows := findAll(table, func(node *nethtml.Node) bool { return isElement(node, "tr") })
	rowTexts := make([]string, 0)
	headerTexts := make([]string, 0)
	for _, row := range rows {
		cells := directCells(row)
		if len(cells) == 0 {
			continue
		}
		hasInput := findFirst(row, func(node *nethtml.Node) bool {
			return isElement(node, "input") || isElement(node, "select") || isElement(node, "textarea")
		}) != nil
		if !hasInput && len(cells) > 1 && len(headerTexts) == 0 {
			rawHeaders := make([]string, 0, len(cells))
			for _, cell := range cells {
				rawHeaders = append(rawHeaders, normalizeText(textContent(cell)))
			}
			if len(rawHeaders) > 1 && rawHeaders[0] == "" {
				rawHeaders = rawHeaders[1:]
			}
			for _, text := range rawHeaders {
				if text != "" {
					headerTexts = append(headerTexts, text)
				}
			}
			continue
		}
		if attr(row, "rowindex") != "" || hasInput {
			if text := firstNonEmpty(textContent(cells[0]), attr(cells[0], "title"), attr(cells[0], "data-title")); text != "" {
				rowTexts = append(rowTexts, text)
			}
		}
	}
	if len(headerTexts) == 0 {
		_, options := matrixTextsFromInputNames(div, questionNum)
		headerTexts = options
	}
	return dedupeTexts(headerTexts), rowTexts
}

func matrixTextsFromInputNames(div *nethtml.Node, questionNum int) ([]string, []string) {
	inputs := findAll(div, func(node *nethtml.Node) bool { return isElement(node, "input") })
	rows := map[int]bool{}
	cols := map[int]bool{}
	for _, input := range inputs {
		match := inputNameMatrixRE.FindStringSubmatch(firstNonEmpty(attr(input, "name"), attr(input, "id")))
		if len(match) < 3 || match[1] != strconv.Itoa(questionNum) {
			continue
		}
		row, _ := strconv.Atoi(match[2])
		rows[row] = true
		if len(match) > 3 && match[3] != "" {
			col, _ := strconv.Atoi(match[3])
			cols[col] = true
		}
	}
	optionTexts := numericLabels(cols)
	rowTexts := itemTitleTexts(div)
	if len(rowTexts) == 0 {
		rowTexts = numericLabels(rows)
	}
	return optionTexts, rowTexts
}

func sliderMatrixTexts(div *nethtml.Node) ([]string, []string) {
	inputs := findAll(div, func(node *nethtml.Node) bool {
		return isElement(node, "input") && classContains(node, "ui-slider-input") && attr(node, "rowid") != ""
	})
	rowTexts := itemTitleTexts(div)
	values := []string{}
	if len(inputs) > 0 {
		minValue := int(floatValue(attr(inputs[0], "min")))
		maxValue := int(floatValue(attr(inputs[0], "max")))
		step := int(floatValue(attr(inputs[0], "step")))
		if step <= 0 {
			step = 1
		}
		for value := minValue; value <= maxValue && len(values) < 200; value += step {
			values = append(values, strconv.Itoa(value))
		}
	}
	return values, rowTexts
}

func directCells(row *nethtml.Node) []*nethtml.Node {
	cells := make([]*nethtml.Node, 0)
	for child := row.FirstChild; child != nil; child = child.NextSibling {
		if isElement(child, "td") || isElement(child, "th") {
			cells = append(cells, child)
		}
	}
	return cells
}

func itemTitleTexts(div *nethtml.Node) []string {
	nodes := findAll(div, func(node *nethtml.Node) bool {
		return classContains(node, "itemTitleSpan") || classContains(node, "itemTitle") || classContains(node, "item-title") || classContains(node, "row-title")
	})
	texts := make([]string, 0, len(nodes))
	for _, node := range nodes {
		if text := normalizeText(textContent(node)); text != "" {
			texts = append(texts, text)
		}
	}
	return dedupeTexts(texts)
}

func numericLabels(values map[int]bool) []string {
	keys := make([]int, 0, len(values))
	for key := range values {
		if key > 0 {
			keys = append(keys, key)
		}
	}
	sort.Ints(keys)
	labels := make([]string, 0, len(keys))
	for _, key := range keys {
		labels = append(labels, strconv.Itoa(key))
	}
	return labels
}

func dedupeTexts(values []string) []string {
	result := make([]string, 0, len(values))
	seen := map[string]bool{}
	for _, value := range values {
		text := normalizeText(value)
		if text == "" || seen[text] {
			continue
		}
		seen[text] = true
		result = append(result, text)
	}
	return result
}

func multiLimits(div *nethtml.Node, typeCode string) (*int, *int) {
	if typeCode != "4" {
		return nil, nil
	}
	text := textContent(div)
	var minPtr *int
	var maxPtr *int
	if match := multiMinMaxRE.FindStringSubmatch(text); len(match) > 2 {
		minValue, _ := strconv.Atoi(match[1])
		maxValue, _ := strconv.Atoi(match[2])
		if minValue > maxValue {
			minValue, maxValue = maxValue, minValue
		}
		minPtr = &minValue
		maxPtr = &maxValue
		return minPtr, maxPtr
	}
	if match := multiMinRE.FindStringSubmatch(text); len(match) > 1 {
		value, _ := strconv.Atoi(match[1])
		if value > 0 {
			minPtr = &value
		}
	}
	if match := multiMaxRE.FindStringSubmatch(text); len(match) > 1 {
		value, _ := strconv.Atoi(match[1])
		if value > 0 {
			maxPtr = &value
		}
	}
	return minPtr, maxPtr
}
