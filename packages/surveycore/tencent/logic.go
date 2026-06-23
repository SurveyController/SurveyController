package tencent

import (
	"strings"

	"surveycontroller/surveycore/internal/model"
)

func attachLogicMetadata(rawQuestions []map[string]any, questions []model.QuestionMeta) []model.QuestionMeta {
	byID := map[string]int{}
	firstByPage := map[string]int{}
	maxNum := 0
	for index, question := range questions {
		if question.ProviderID == "" || question.IsDescription {
			continue
		}
		byID[question.ProviderID] = index
		if question.ProviderPageID != "" {
			if _, ok := firstByPage[question.ProviderPageID]; !ok {
				firstByPage[question.ProviderPageID] = question.Num
			}
		}
		if question.Num > maxNum {
			maxNum = question.Num
		}
	}
	inbound := map[string][]map[string]any{}
	controls := map[string][]map[string]any{}
	for _, raw := range rawQuestions {
		sourceID := strings.TrimSpace(stringValue(raw["id"]))
		idx, ok := byID[sourceID]
		if !ok {
			continue
		}
		question := questions[idx]
		jumpRules := make([]map[string]any, 0)
		hasJump := false
		exact := false
		if target, ok := resolveTarget(raw["goto"], byIDNum(questions), firstByPage, maxNum); ok {
			jumpRules = append(jumpRules, map[string]any{"option_index": -1, "jumpto": target, "option_text": nil})
			hasJump = true
			exact = true
		} else if raw["goto"] != nil && stringValue(raw["goto"]) != "" {
			hasJump = true
		}
		for optionIndex, option := range asMapList(raw["options"]) {
			if target, ok := resolveTarget(option["goto"], byIDNum(questions), firstByPage, maxNum); ok {
				jumpRules = append(jumpRules, map[string]any{
					"option_index": optionIndex,
					"jumpto":       target,
					"option_text":  cleanOptionText(option["text"]),
				})
				hasJump = true
				exact = true
			} else if option["goto"] != nil && stringValue(option["goto"]) != "" {
				hasJump = true
			}
			for _, targetID := range collectQuestionRefs(option["display"]) {
				targetIndex, exists := byID[targetID]
				if !exists {
					continue
				}
				targetNum := questions[targetIndex].Num
				controls[sourceID] = append(controls[sourceID], map[string]any{
					"target_question_num":      targetNum,
					"condition_option_indices": []int{optionIndex},
					"condition_mode":           "selected",
				})
				inbound[targetID] = append(inbound[targetID], map[string]any{
					"condition_question_num":   question.Num,
					"condition_option_indices": []int{optionIndex},
					"condition_mode":           "selected",
				})
				exact = true
			}
		}
		question.HasJump = hasJump || len(jumpRules) > 0
		question.JumpRules = jumpRules
		if items := controls[sourceID]; len(items) > 0 {
			question.HasDependentDisplayLogic = true
			question.ControlsDisplayTargets = items
			exact = true
		}
		if hasAnyLogic(question) {
			if exact {
				question.LogicStatus = model.LogicParseStatusComplete
			} else {
				question.LogicStatus = model.LogicParseStatusUnknown
			}
		} else {
			question.LogicStatus = model.LogicParseStatusNone
		}
		questions[idx] = question
	}
	for id, conditions := range inbound {
		idx, ok := byID[id]
		if !ok {
			continue
		}
		questions[idx].HasDisplayCondition = true
		questions[idx].DisplayConditions = conditions
		questions[idx].LogicStatus = model.LogicParseStatusComplete
	}
	for _, raw := range rawQuestions {
		id := strings.TrimSpace(stringValue(raw["id"]))
		idx, ok := byID[id]
		if !ok {
			continue
		}
		if raw["hidden"] != nil && raw["hidden"] != "" {
			questions[idx].HasDisplayCondition = true
			if questions[idx].LogicStatus == model.LogicParseStatusNone {
				questions[idx].LogicStatus = model.LogicParseStatusUnknown
			}
		}
	}
	return questions
}

func byIDNum(questions []model.QuestionMeta) map[string]int {
	result := map[string]int{}
	for _, question := range questions {
		if question.ProviderID != "" && !question.IsDescription {
			result[question.ProviderID] = question.Num
		}
	}
	return result
}

func resolveTarget(raw any, questionByID map[string]int, firstByPage map[string]int, maxNum int) (int, bool) {
	if raw == nil || raw == "" {
		return 0, false
	}
	if value := intValue(raw); value > 0 {
		return value, true
	}
	for _, id := range collectQuestionRefs(raw) {
		if value := questionByID[id]; value > 0 {
			return value, true
		}
	}
	for _, id := range collectPageRefs(raw) {
		if value := firstByPage[id]; value > 0 {
			return value, true
		}
	}
	lowered := strings.ToLower(stringValue(raw))
	for _, token := range []string{"submit", "finish", "complete", "end", "结束", "提交", "完成"} {
		if strings.Contains(lowered, token) {
			return maxNum + 1, true
		}
	}
	return 0, false
}

func collectQuestionRefs(value any) []string {
	return uniqueMatches(questionIDTokenRE.FindAllString(stringValue(value), -1))
}

func collectPageRefs(value any) []string {
	return uniqueMatches(pageIDTokenRE.FindAllString(stringValue(value), -1))
}

func uniqueMatches(values []string) []string {
	result := make([]string, 0, len(values))
	seen := map[string]bool{}
	for _, value := range values {
		text := strings.TrimSpace(value)
		if text == "" || seen[text] {
			continue
		}
		seen[text] = true
		result = append(result, text)
	}
	return result
}

func hasAnyLogic(question model.QuestionMeta) bool {
	return question.HasJump || question.HasDisplayCondition || question.HasDependentDisplayLogic
}
