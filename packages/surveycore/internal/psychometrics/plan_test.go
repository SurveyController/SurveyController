package psychometrics

import (
	"testing"

	"surveycontroller/surveycore/internal/model"
)

func TestBuildJointPlanAppliesScaleSamples(t *testing.T) {
	q1 := 1
	q2 := 2
	cfg := &model.RuntimeConfig{
		Target:                 12,
		ReliabilityModeEnabled: true,
		PsychoTargetAlpha:      0.85,
		QuestionsInfo: []model.QuestionMeta{
			{Num: 1, ProviderType: "scale", TypeCode: "5", Options: 5},
			{Num: 2, ProviderType: "scale", TypeCode: "5", Options: 5},
		},
		QuestionEntries: []model.QuestionEntry{
			{QuestionType: "scale", QuestionNum: &q1, Probabilities: []float64{1, 1, 1, 1, 1}},
			{QuestionType: "scale", QuestionNum: &q2, Probabilities: []float64{1, 1, 1, 1, 1}},
		},
	}

	plan := BuildJointPlan(cfg)
	if plan == nil {
		t.Fatal("plan is nil")
	}
	entries := ApplySample(cfg.QuestionEntries, cfg.QuestionsInfo, plan, 0)
	if len(entries) != 2 {
		t.Fatalf("entries = %#v", entries)
	}
	for _, entry := range entries {
		values, ok := entry.Probabilities.([]float64)
		if !ok || len(values) != 5 {
			t.Fatalf("probabilities = %#v", entry.Probabilities)
		}
		total := 0.0
		ones := 0
		for _, value := range values {
			total += value
			if value == 1 {
				ones++
			}
		}
		if total != 1 || ones != 1 {
			t.Fatalf("probabilities = %#v", values)
		}
	}
}

func TestBuildJointPlanSkipsPlainSingleWithoutOrdinalOptions(t *testing.T) {
	q1 := 1
	q2 := 2
	cfg := &model.RuntimeConfig{
		Target:                 5,
		ReliabilityModeEnabled: true,
		QuestionsInfo: []model.QuestionMeta{
			{Num: 1, ProviderType: "single", TypeCode: "3", Options: 2, OptionTexts: []string{"苹果", "香蕉"}},
			{Num: 2, ProviderType: "single", TypeCode: "3", Options: 2, OptionTexts: []string{"红色", "蓝色"}},
		},
		QuestionEntries: []model.QuestionEntry{
			{QuestionType: "single", QuestionNum: &q1, Probabilities: []float64{1, 1}},
			{QuestionType: "single", QuestionNum: &q2, Probabilities: []float64{1, 1}},
		},
	}
	if plan := BuildJointPlan(cfg); plan != nil {
		t.Fatalf("plan = %#v", plan)
	}
}
