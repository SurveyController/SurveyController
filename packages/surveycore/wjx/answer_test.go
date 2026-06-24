package wjx

import (
	"strings"
	"testing"

	"surveycontroller/surveycore/internal/model"
)

func TestBuildSubmitDataAppliesAnswerRules(t *testing.T) {
	q1 := 1
	q2 := 2
	data, err := buildSubmitData([]model.QuestionMeta{
		{Num: 1, Provider: model.ProviderWJX, ProviderType: "single", TypeCode: "3", Options: 2},
		{Num: 2, Provider: model.ProviderWJX, ProviderType: "single", TypeCode: "3", Options: 3},
	}, &model.RuntimeConfig{
		QuestionEntries: []model.QuestionEntry{
			{QuestionType: "single", QuestionNum: &q1, Probabilities: []float64{0, 1}},
			{QuestionType: "single", QuestionNum: &q2, Probabilities: []float64{1, 1, 1}},
		},
		AnswerRules: []map[string]any{{
			"condition_question_num":   1,
			"condition_mode":           "selected",
			"condition_option_indices": []any{1},
			"target_question_num":      2,
			"action_mode":              "must_select",
			"target_option_indices":    []any{2},
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(data, "1$2") || !strings.Contains(data, "2$3") {
		t.Fatalf("submitdata = %q", data)
	}
}
