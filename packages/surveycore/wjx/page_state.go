package wjx

import "strings"

func pageStateError(htmlText string) error {
	text := normalizeText(htmlText)
	compact := strings.ReplaceAll(text, " ", "")
	if strings.Contains(text, "已暂停") && (strings.Contains(text, "不能填写") || strings.Contains(text, "问卷已暂停")) {
		return ParseError{Message: "问卷已暂停，需要前往问卷星后台重新发布"}
	}
	if strings.Contains(compact, "此问卷处于停止状态，无法作答") {
		return ParseError{Message: "问卷已停止，无法作答"}
	}
	if strings.Contains(compact, "企业标准版") &&
		strings.Contains(compact, "问卷发布者") &&
		(strings.Contains(compact, "未购买") || strings.Contains(compact, "已到期")) &&
		(strings.Contains(compact, "暂时不能被填写") || strings.Contains(compact, "暂时不能填写")) {
		return ParseError{Message: "问卷发布者企业标准版未购买或已到期，暂时不能填写"}
	}
	if !strings.Contains(htmlText, "id=\"divQuestion\"") && !strings.Contains(htmlText, "id='divQuestion'") {
		if strings.Contains(compact, "此问卷将于") || strings.Contains(compact, "尚未开始") || strings.Contains(compact, "未开放") {
			return ParseError{Message: "该问卷暂未开放，无法解析"}
		}
	}
	return nil
}
