package credamo

import (
	"encoding/json"
	"testing"

	"surveycontroller/surveycore/internal/model"
)

func TestBuildAnswerItemsMatchesEntryByProviderQuestionID(t *testing.T) {
	questionNum := 99
	providerID := "102"
	raw := []map[string]any{
		{
			"qstNo":        "Q2",
			"qstId":        102,
			"sortNo":       2,
			"questionType": 2,
			"selector":     1,
			"choices":      []any{map[string]any{"choiceId": 1}, map[string]any{"choiceId": 2}},
		},
	}
	cfg := &model.RuntimeConfig{
		QuestionEntries: []model.QuestionEntry{
			{
				QuestionType:       "single",
				QuestionNum:        &questionNum,
				ProviderQuestionID: &providerID,
				Probabilities:      []float64{0, 1},
			},
		},
	}

	items, err := buildAnswerItems(raw, cfg)
	if err != nil {
		t.Fatal(err)
	}
	choice := items[0]["answerQstChoice"].(map[string]any)
	if choice["choiceId"] != 2 {
		t.Fatalf("choice = %#v", choice)
	}
}

func TestBuildAnswerItemsUsesJSONProbabilityValues(t *testing.T) {
	var entry model.QuestionEntry
	if err := json.Unmarshal([]byte(`{"question_type":"multiple","probabilities":[100,0,100]}`), &entry); err != nil {
		t.Fatal(err)
	}
	questionNum := 1
	entry.QuestionNum = &questionNum
	raw := []map[string]any{
		{
			"qstNo":        "Q1",
			"qstId":        101,
			"questionType": 2,
			"selector":     2,
			"choices": []any{
				map[string]any{"choiceId": 1},
				map[string]any{"choiceId": 2},
				map[string]any{"choiceId": 3},
			},
		},
	}
	cfg := &model.RuntimeConfig{QuestionEntries: []model.QuestionEntry{entry}}

	items, err := buildAnswerItems(raw, cfg)
	if err != nil {
		t.Fatal(err)
	}
	choices := items[0]["answerQstChoiceList"].([]map[string]any)
	if len(choices) != 2 || choices[0]["choiceId"] != 1 || choices[1]["choiceId"] != 3 {
		t.Fatalf("choices = %#v", choices)
	}
}

func TestBuildAnswerItemsCoversOrderAndMatrixDefaults(t *testing.T) {
	cfg := &model.RuntimeConfig{}
	items, err := buildAnswerItems([]map[string]any{
		{
			"qstNo":        "Q1",
			"qstId":        101,
			"sortNo":       2,
			"questionType": 6,
			"choices": []any{
				map[string]any{"choiceId": 1},
				map[string]any{"choiceId": 2},
			},
		},
		{
			"qstNo":        "Q2",
			"qstId":        102,
			"sortNo":       1,
			"questionType": 4,
			"choices":      []any{map[string]any{"choiceId": 3}, map[string]any{"choiceId": 4}},
			"answers":      []any{map[string]any{"answerId": 5}, map[string]any{"answerId": 6}},
		},
	}, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if items[0]["qstId"] != 102 || items[1]["qstId"] != 101 {
		t.Fatalf("items not sorted by sortNo: %#v", items)
	}
	matrixRows := items[0]["answerQstChoiceList"].([]map[string]any)
	if len(matrixRows) != 2 {
		t.Fatalf("matrix rows = %#v", matrixRows)
	}
	orderRows := items[1]["answerChoiceContent"].([]map[string]any)
	if len(orderRows) != 2 || orderRows[0]["choiceId"] != 1 || orderRows[1]["choiceId"] != 2 {
		t.Fatalf("order rows = %#v", orderRows)
	}
}

func TestBuildAnswerItemsUsesMatrixRowProbabilities(t *testing.T) {
	questionNum := 1
	cfg := &model.RuntimeConfig{QuestionEntries: []model.QuestionEntry{{
		QuestionType:  "matrix",
		QuestionNum:   &questionNum,
		Probabilities: [][]float64{{0, 1}, {1, 0}},
	}}}
	items, err := buildAnswerItems([]map[string]any{
		{
			"qstNo":        "Q1",
			"qstId":        102,
			"questionType": 4,
			"choices":      []any{map[string]any{"choiceId": 3}, map[string]any{"choiceId": 4}},
			"answers":      []any{map[string]any{"answerId": 5}, map[string]any{"answerId": 6}},
		},
	}, cfg)
	if err != nil {
		t.Fatal(err)
	}
	rows := items[0]["answerQstChoiceList"].([]map[string]any)
	first := rows[0]["choiceAnswerList"].([]map[string]any)[0]
	second := rows[1]["choiceAnswerList"].([]map[string]any)[0]
	if first["answerId"] != 6 || second["answerId"] != 5 {
		t.Fatalf("matrix rows = %#v", rows)
	}
}

func TestBuildAnswerItemsAppliesAnswerRules(t *testing.T) {
	q1 := 1
	q2 := 2
	cfg := &model.RuntimeConfig{
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
	}
	items, err := buildAnswerItems([]map[string]any{
		{
			"qstNo":        "Q1",
			"qstId":        101,
			"sortNo":       1,
			"questionType": 2,
			"selector":     1,
			"choices":      []any{map[string]any{"choiceId": 1}, map[string]any{"choiceId": 2}},
		},
		{
			"qstNo":        "Q2",
			"qstId":        102,
			"sortNo":       2,
			"questionType": 2,
			"selector":     1,
			"choices":      []any{map[string]any{"choiceId": 3}, map[string]any{"choiceId": 4}, map[string]any{"choiceId": 5}},
		},
	}, cfg)
	if err != nil {
		t.Fatal(err)
	}
	first := items[0]["answerQstChoice"].(map[string]any)
	second := items[1]["answerQstChoice"].(map[string]any)
	if first["choiceId"] != 2 || second["choiceId"] != 5 {
		t.Fatalf("items = %#v", items)
	}
}
