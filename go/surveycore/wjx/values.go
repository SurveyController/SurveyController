package wjx

import (
	"encoding/json"
	"fmt"
	stdhtml "html"
	"math"
	"regexp"
	"strconv"
	"strings"

	nethtml "golang.org/x/net/html"
)

var (
	spaceRE           = regexp.MustCompile(`\s+`)
	leadingNumberRE   = regexp.MustCompile(`^\*?\s*\d+\.\s*`)
	displayNumberRE   = regexp.MustCompile(`^\*?\s*(\d+)\.\s*`)
	multiMinMaxRE     = regexp.MustCompile(`(?:至少|最少|不少于)\s*选?\s*(\d+)\s*项?.*?(?:最多|至多|不超过)\s*选?\s*(\d+)\s*项?`)
	multiMinRE        = regexp.MustCompile(`(?:至少|最少|不少于)\s*选?\s*(\d+)\s*项?`)
	multiMaxRE        = regexp.MustCompile(`(?:最多|至多|不超过)\s*选?\s*(\d+)\s*项?`)
	divNumberRE       = regexp.MustCompile(`div(\d+)`)
	inputNameMatrixRE = regexp.MustCompile(`q(\d+)[_-](\d+)(?:[_-](\d+))?`)
)

func stringValue(value any) string {
	switch typed := value.(type) {
	case nil:
		return ""
	case string:
		return typed
	case fmt.Stringer:
		return typed.String()
	case float64:
		if math.Trunc(typed) == typed {
			return strconv.FormatInt(int64(typed), 10)
		}
		return strconv.FormatFloat(typed, 'f', -1, 64)
	case float32:
		return strconv.FormatFloat(float64(typed), 'f', -1, 32)
	case int:
		return strconv.Itoa(typed)
	case int64:
		return strconv.FormatInt(typed, 10)
	case bool:
		return strconv.FormatBool(typed)
	default:
		return fmt.Sprint(typed)
	}
}

func intValue(value any) int {
	switch typed := value.(type) {
	case int:
		return typed
	case int64:
		return int(typed)
	case float64:
		return int(typed)
	case float32:
		return int(typed)
	case json.Number:
		number, _ := typed.Int64()
		return int(number)
	case string:
		number, err := strconv.Atoi(strings.TrimSpace(typed))
		if err == nil {
			return number
		}
	}
	return 0
}

func floatValue(value any) float64 {
	switch typed := value.(type) {
	case int:
		return float64(typed)
	case int64:
		return float64(typed)
	case float64:
		return typed
	case float32:
		return float64(typed)
	case json.Number:
		number, _ := typed.Float64()
		return number
	case string:
		number, err := strconv.ParseFloat(strings.TrimSpace(typed), 64)
		if err == nil {
			return number
		}
	}
	return 0
}

func normalizeText(value any) string {
	text := strings.TrimSpace(stringValue(value))
	if text == "" {
		return ""
	}
	text = stdhtml.UnescapeString(text)
	return strings.TrimSpace(spaceRE.ReplaceAllString(text, " "))
}

func cleanupTitle(value string) string {
	title := normalizeText(value)
	title = leadingNumberRE.ReplaceAllString(title, "")
	title = strings.ReplaceAll(title, "【单选题】", "")
	title = strings.ReplaceAll(title, "【多选题】", "")
	return normalizeText(title)
}

func displayNumber(value string) int {
	match := displayNumberRE.FindStringSubmatch(normalizeText(value))
	if len(match) < 2 {
		return 0
	}
	number, _ := strconv.Atoi(match[1])
	return number
}

func parseHTML(raw string) (*nethtml.Node, error) {
	return nethtml.Parse(strings.NewReader(raw))
}

func attr(node *nethtml.Node, key string) string {
	if node == nil {
		return ""
	}
	for _, item := range node.Attr {
		if strings.EqualFold(item.Key, key) {
			return item.Val
		}
	}
	return ""
}

func hasAttr(node *nethtml.Node, key string) bool {
	if node == nil {
		return false
	}
	for _, item := range node.Attr {
		if strings.EqualFold(item.Key, key) {
			return true
		}
	}
	return false
}

func hasClass(node *nethtml.Node, className string) bool {
	classes := strings.Fields(attr(node, "class"))
	for _, item := range classes {
		if strings.EqualFold(item, className) {
			return true
		}
	}
	return false
}

func classContains(node *nethtml.Node, fragment string) bool {
	return strings.Contains(strings.ToLower(attr(node, "class")), strings.ToLower(fragment))
}

func isElement(node *nethtml.Node, tag string) bool {
	return node != nil && node.Type == nethtml.ElementNode && strings.EqualFold(node.Data, tag)
}

func textContent(node *nethtml.Node) string {
	var parts []string
	var walk func(*nethtml.Node)
	walk = func(current *nethtml.Node) {
		if current == nil {
			return
		}
		if current.Type == nethtml.TextNode {
			if text := normalizeText(current.Data); text != "" {
				parts = append(parts, text)
			}
		}
		for child := current.FirstChild; child != nil; child = child.NextSibling {
			walk(child)
		}
	}
	walk(node)
	return normalizeText(strings.Join(parts, " "))
}

func findFirst(node *nethtml.Node, match func(*nethtml.Node) bool) *nethtml.Node {
	if node == nil {
		return nil
	}
	if match(node) {
		return node
	}
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		if found := findFirst(child, match); found != nil {
			return found
		}
	}
	return nil
}

func findAll(node *nethtml.Node, match func(*nethtml.Node) bool) []*nethtml.Node {
	var result []*nethtml.Node
	var walk func(*nethtml.Node)
	walk = func(current *nethtml.Node) {
		if current == nil {
			return
		}
		if match(current) {
			result = append(result, current)
		}
		for child := current.FirstChild; child != nil; child = child.NextSibling {
			walk(child)
		}
	}
	walk(node)
	return result
}

func directElementChildren(node *nethtml.Node) []*nethtml.Node {
	var result []*nethtml.Node
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		if child.Type == nethtml.ElementNode {
			result = append(result, child)
		}
	}
	return result
}

func containsInputType(node *nethtml.Node, types map[string]bool) bool {
	return findFirst(node, func(candidate *nethtml.Node) bool {
		if !isElement(candidate, "input") {
			return false
		}
		return types[strings.ToLower(attr(candidate, "type"))]
	}) != nil
}

func containsTextInput(node *nethtml.Node) bool {
	return findFirst(node, isTextInputNode) != nil
}

func isTextInputNode(node *nethtml.Node) bool {
	if node == nil || node.Type != nethtml.ElementNode {
		return false
	}
	style := strings.ReplaceAll(strings.ToLower(attr(node, "style")), " ", "")
	if strings.Contains(style, "display:none") || strings.Contains(style, "visibility:hidden") {
		return false
	}
	if isElement(node, "textarea") {
		return true
	}
	if isElement(node, "input") {
		inputType := strings.ToLower(attr(node, "type"))
		return inputType == "" || inputType == "text" || inputType == "search" || inputType == "tel" || inputType == "number" || inputType == "email" || inputType == "url" || inputType == "password"
	}
	if attr(node, "contenteditable") == "true" {
		return true
	}
	return classContains(node, "textcont") || classContains(node, "textedit")
}

func maxInt(left int, right int) int {
	if left > right {
		return left
	}
	return right
}

func minInt(left int, right int) int {
	if left < right {
		return left
	}
	return right
}
