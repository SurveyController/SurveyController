package wjx

import (
	"fmt"
	"sort"
	"strconv"
	"strings"

	"surveycontroller/surveycore/internal/answerplan"
	"surveycontroller/surveycore/internal/model"
)

type answerAction struct {
	QuestionNum int
	Kind        string
	Indices     []int
	Matrix      []int
	Texts       []string
	SliderValue string
	OptionFills map[int]string
}

func toWJXAction(action answerplan.Action) answerAction {
	return answerAction{
		QuestionNum: action.QuestionNum,
		Kind:        action.Kind,
		Indices:     append([]int(nil), action.SelectedIndices...),
		Matrix:      append([]int(nil), action.MatrixIndices...),
		Texts:       append([]string(nil), action.TextValues...),
		SliderValue: action.SliderValue,
		OptionFills: cloneOptionFills(action.OptionFillTexts),
	}
}

func cloneOptionFills(src map[int]string) map[int]string {
	dst := map[int]string{}
	for key, value := range src {
		dst[key] = value
	}
	return dst
}

func buildSubmitData(questions []model.QuestionMeta, cfg *model.RuntimeConfig) (string, error) {
	planned, err := answerplan.BuildActionsWithLogic(questions, cfg.QuestionEntries, answerplan.OptionsFromRuntimeConfig(cfg))
	if err != nil {
		return "", err
	}
	actions := make([]answerAction, 0, len(questions))
	for _, action := range planned {
		wjxAction := toWJXAction(action)
		if wjxAction.QuestionNum > 0 && actionAnswer(wjxAction) != "" {
			actions = append(actions, wjxAction)
		}
	}
	sort.SliceStable(actions, func(i int, j int) bool { return actions[i].QuestionNum < actions[j].QuestionNum })
	parts := make([]string, 0, len(actions))
	for _, action := range actions {
		answer := strings.ReplaceAll(actionAnswer(action), "，", ",")
		if answer != "" {
			parts = append(parts, fmt.Sprintf("%d$%s", action.QuestionNum, answer))
		}
	}
	if len(parts) == 0 {
		return "", fmt.Errorf("问卷星没有生成可提交答案")
	}
	return strings.Join(parts, "}"), nil
}

func actionAnswer(action answerAction) string {
	switch action.Kind {
	case "choice", "select", "single", "dropdown", "scale", "multiple":
		parts := make([]string, 0, len(action.Indices))
		for _, index := range action.Indices {
			value := strconv.Itoa(index + 1)
			if fill := strings.TrimSpace(action.OptionFills[index]); fill != "" {
				value += "!" + fill
			}
			parts = append(parts, value)
		}
		return strings.Join(parts, "|")
	case "matrix":
		parts := make([]string, 0, len(action.Matrix))
		for row, index := range action.Matrix {
			parts = append(parts, fmt.Sprintf("%d!%d", row+1, index+1))
		}
		return strings.Join(parts, ",")
	case "text", "multi_text":
		return strings.Join(action.Texts, "^")
	case "slider":
		return action.SliderValue
	case "order":
		parts := make([]string, 0, len(action.Indices))
		for _, index := range action.Indices {
			parts = append(parts, strconv.Itoa(index+1))
		}
		return strings.Join(parts, ",")
	default:
		return ""
	}
}
