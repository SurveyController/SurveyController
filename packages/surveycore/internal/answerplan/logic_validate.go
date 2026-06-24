package answerplan

import (
	"fmt"
	"strings"

	"surveycontroller/surveycore/internal/model"
)

func httpLogicFallbackReason(questions []model.QuestionMeta) string {
	maxNum := maxQuestionNum(questions)
	for _, question := range questions {
		if question.Num <= 0 || !questionHasLogic(question) {
			continue
		}
		if !logicStatusCompleteEnough(question) {
			return fmt.Sprintf("第%d题逻辑规则未完整解析", question.Num)
		}
		for _, condition := range question.DisplayConditions {
			sourceNum := intValue(condition["condition_question_num"], 0)
			mode := strings.TrimSpace(stringValue(condition["condition_mode"]))
			if mode == "" {
				mode = conditionSelected
			}
			if sourceNum <= 0 {
				return fmt.Sprintf("第%d题显隐条件缺少来源题号", question.Num)
			}
			if sourceNum >= question.Num {
				return fmt.Sprintf("第%d题显隐条件依赖未来题目", question.Num)
			}
			if mode != conditionSelected && mode != conditionNotSelected {
				return fmt.Sprintf("第%d题显隐条件模式不支持：%s", question.Num, mode)
			}
		}
		for _, target := range question.ControlsDisplayTargets {
			targetNum := intValue(target["target_question_num"], 0)
			mode := strings.TrimSpace(stringValue(target["condition_mode"]))
			if mode == "" {
				mode = conditionSelected
			}
			if targetNum <= question.Num {
				return fmt.Sprintf("第%d题控制显示规则存在回跳", question.Num)
			}
			if mode != conditionSelected && mode != conditionNotSelected {
				return fmt.Sprintf("第%d题控制显示模式不支持：%s", question.Num, mode)
			}
		}
		for _, rule := range question.JumpRules {
			jumpTarget := intValue(rule["jumpto"], 0)
			if jumpRuleTerminates(rule) {
				continue
			}
			if jumpTarget <= question.Num {
				return fmt.Sprintf("第%d题跳题目标回跳到已过题目", question.Num)
			}
			if maxNum > 0 && jumpTarget > maxNum+1 {
				return fmt.Sprintf("第%d题跳题目标超出问卷范围", question.Num)
			}
		}
	}
	return ""
}

func questionHasLogic(question model.QuestionMeta) bool {
	return question.HasJump || question.HasDisplayCondition || question.HasDependentDisplayLogic
}

func logicStatusCompleteEnough(question model.QuestionMeta) bool {
	status := strings.ToLower(strings.TrimSpace(question.LogicStatus))
	if status == model.LogicParseStatusComplete {
		return true
	}
	if status != model.LogicParseStatusUnknown {
		return false
	}
	if question.HasJump && len(question.JumpRules) == 0 {
		return false
	}
	if question.HasDisplayCondition && len(question.DisplayConditions) == 0 {
		return false
	}
	if question.HasDependentDisplayLogic && len(question.ControlsDisplayTargets) == 0 {
		return false
	}
	return true
}
