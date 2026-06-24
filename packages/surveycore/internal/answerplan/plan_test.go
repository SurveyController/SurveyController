package answerplan

import (
	"regexp"
	"strings"
	"testing"

	"surveycontroller/surveycore/internal/model"
)

type fakeAnswerRuntime struct {
	total  int
	counts []int
}

func (f fakeAnswerRuntime) SnapshotDistributionStats(_ string, optionCount int) (int, []int) {
	counts := make([]int, optionCount)
	copy(counts, f.counts)
	return f.total, counts
}

func (f fakeAnswerRuntime) AppendPendingDistributionChoice(_ string, _ string, _ int, _ int) {}
func (f fakeAnswerRuntime) CommitPendingDistribution(_ string) int                           { return 0 }
func (f fakeAnswerRuntime) ResetPendingDistribution(_ string)                                {}

func TestBuildActionUsesMatrixRowProbabilities(t *testing.T) {
	action, err := BuildAction(model.QuestionMeta{
		Num:          3,
		ProviderType: "matrix",
		TypeCode:     "6",
		Rows:         2,
		Options:      2,
	}, model.QuestionEntry{
		QuestionType:  "matrix",
		Probabilities: [][]float64{{0, 1}, {1, 0}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(action.MatrixIndices) != 2 || action.MatrixIndices[0] != 1 || action.MatrixIndices[1] != 0 {
		t.Fatalf("matrix indices = %#v", action.MatrixIndices)
	}
}

func TestBuildActionsAppliesAnswerRuleToLaterQuestion(t *testing.T) {
	q1 := 1
	q2 := 2
	actions, err := BuildActions([]model.QuestionMeta{
		{Num: 1, ProviderType: "single", TypeCode: "3", Options: 2},
		{Num: 2, ProviderType: "single", TypeCode: "3", Options: 3},
	}, []model.QuestionEntry{
		{QuestionType: "single", QuestionNum: &q1, Probabilities: []float64{0, 1}},
		{QuestionType: "single", QuestionNum: &q2, Probabilities: []float64{1, 1, 1}},
	}, BuildOptions{AnswerRules: []map[string]any{{
		"condition_question_num":   1,
		"condition_mode":           "selected",
		"condition_option_indices": []any{1},
		"target_question_num":      2,
		"action_mode":              "must_select",
		"target_option_indices":    []any{2},
	}}})
	if err != nil {
		t.Fatal(err)
	}
	if len(actions) != 2 || len(actions[1].SelectedIndices) != 1 || actions[1].SelectedIndices[0] != 2 {
		t.Fatalf("actions = %#v", actions)
	}
}

func TestBuildActionsAppliesMatrixRowAnswerRule(t *testing.T) {
	q1 := 1
	q2 := 2
	actions, err := BuildActions([]model.QuestionMeta{
		{Num: 1, ProviderType: "matrix", TypeCode: "6", Options: 2, Rows: 2},
		{Num: 2, ProviderType: "matrix", TypeCode: "6", Options: 2, Rows: 2},
	}, []model.QuestionEntry{
		{QuestionType: "matrix", QuestionNum: &q1, Probabilities: [][]float64{{1, 0}, {0, 1}}},
		{QuestionType: "matrix", QuestionNum: &q2, Probabilities: [][]float64{{1, 1}, {1, 1}}},
	}, BuildOptions{AnswerRules: []map[string]any{{
		"condition_question_num":   1,
		"condition_mode":           "selected",
		"condition_option_indices": []any{1},
		"condition_row_index":      1,
		"target_question_num":      2,
		"action_mode":              "must_not_select",
		"target_option_indices":    []any{0},
		"target_row_index":         0,
	}}})
	if err != nil {
		t.Fatal(err)
	}
	if len(actions) != 2 || len(actions[1].MatrixIndices) != 2 || actions[1].MatrixIndices[0] != 1 {
		t.Fatalf("actions = %#v", actions)
	}
}

func TestSelectedIndicesUsesPercentProbabilities(t *testing.T) {
	selected := SelectedIndices(model.QuestionEntry{Probabilities: []float64{100, 0, 0}}, 3, 1, 3)
	if len(selected) != 1 || selected[0] != 0 {
		t.Fatalf("selected = %#v", selected)
	}
	selected = SelectedIndices(model.QuestionEntry{Probabilities: []float64{0, 0, 100}}, 3, 1, 3)
	if len(selected) != 1 || selected[0] != 2 {
		t.Fatalf("selected = %#v", selected)
	}
	for index := 0; index < 20; index++ {
		selected = SelectedIndices(model.QuestionEntry{Probabilities: []float64{100, 100, 100}}, 3, 1, 2)
		if len(selected) > 2 || len(selected) == 0 {
			t.Fatalf("selected = %#v", selected)
		}
	}
}

func TestResolveDistributionProbabilitiesBoostsUnderservedOption(t *testing.T) {
	values := resolveDistributionProbabilities([]float64{1, 1}, 2, fakeAnswerRuntime{
		total:  12,
		counts: []int{12, 0},
	}, 1, nil)
	if len(values) != 2 || values[1] <= values[0] {
		t.Fatalf("values = %#v", values)
	}
}

func TestApplyPersonaBoostMatchesKeywords(t *testing.T) {
	values := applyPersonaBoost([]string{"男", "女"}, []float64{1, 1}, &model.Persona{Gender: "女"})
	if len(values) != 2 || values[1] <= values[0] {
		t.Fatalf("values = %#v", values)
	}
}

func TestApplyDimensionTendencyReusesDimensionBase(t *testing.T) {
	bases := map[string]float64{}
	first := applyDimensionTendency([]float64{0, 0, 0, 0, 1}, 5, "服务", bases, nil)
	second := applyDimensionTendency([]float64{1, 1, 1, 1, 1}, 5, "服务", bases, nil)
	if len(first) != 5 || len(second) != 5 || second[4] <= second[0] {
		t.Fatalf("first=%#v second=%#v bases=%#v", first, second, bases)
	}
}

func TestOptionFillTextFallsBackForFillableOption(t *testing.T) {
	question := model.QuestionMeta{FillableOptions: []int{1}}
	entry := model.QuestionEntry{}
	if got := OptionFillText(entry, question, 1); got != defaultFillText {
		t.Fatalf("fill text = %q", got)
	}
}

func TestResolveTextValuesUsesPersonaForIDCardGender(t *testing.T) {
	values := ResolveTextValuesWithPersona(model.QuestionEntry{
		QuestionType: "text",
		Texts:        []string{randomIDCardToken},
	}, model.QuestionMeta{Num: 1, ProviderType: "text", TextInputs: 1}, 1, &model.Persona{Gender: "女", AgeGroup: "26-35"})
	if len(values) != 1 || len(values[0]) != 18 {
		t.Fatalf("values = %#v", values)
	}
	genderDigit := values[0][16] - '0'
	if genderDigit%2 != 0 {
		t.Fatalf("id card = %q", values[0])
	}
}

func TestBuildActionsMultipleRuleMustSelectOverridesZeroWeight(t *testing.T) {
	q1 := 1
	q2 := 2
	actions, err := BuildActions([]model.QuestionMeta{
		{Num: 1, ProviderType: "single", TypeCode: "3", Options: 2},
		{Num: 2, ProviderType: "multiple", TypeCode: "4", Options: 3},
	}, []model.QuestionEntry{
		{QuestionType: "single", QuestionNum: &q1, Probabilities: []float64{0, 1}},
		{QuestionType: "multiple", QuestionNum: &q2, Probabilities: []float64{0, 0, 0}},
	}, BuildOptions{AnswerRules: []map[string]any{{
		"condition_question_num":   1,
		"condition_mode":           "selected",
		"condition_option_indices": []any{1},
		"target_question_num":      2,
		"action_mode":              "must_select",
		"target_option_indices":    []any{2},
	}}})
	if err != nil {
		t.Fatal(err)
	}
	if len(actions) != 2 || len(actions[1].SelectedIndices) != 1 || actions[1].SelectedIndices[0] != 2 {
		t.Fatalf("actions = %#v", actions)
	}
}

func TestBuildActionResolvesTextCandidatesAndBlankModes(t *testing.T) {
	action, err := BuildAction(model.QuestionMeta{
		Num:          1,
		ProviderType: "multi_text",
		TypeCode:     "9",
		TextInputs:   3,
	}, model.QuestionEntry{
		QuestionType:            "multi_text",
		Probabilities:           []float64{0, 1},
		Texts:                   []string{"甲||乙||丙", "A||B||C"},
		MultiTextBlankModes:     []string{"none", "mobile", "integer"},
		MultiTextBlankIntRanges: [][]int{{}, {}, {7, 7}},
	})
	if err != nil {
		t.Fatal(err)
	}
	mobileRE := regexp.MustCompile(`^1\d{10}$`)
	if len(action.TextValues) != 3 || action.TextValues[0] != "A" || !mobileRE.MatchString(action.TextValues[1]) || action.TextValues[2] != "7" {
		t.Fatalf("text values = %#v", action.TextValues)
	}
}

func TestBuildActionResolvesTextRandomMode(t *testing.T) {
	action, err := BuildAction(model.QuestionMeta{
		Num:          1,
		ProviderType: "text",
		TypeCode:     "1",
		TextInputs:   1,
	}, model.QuestionEntry{
		QuestionType:       "text",
		Probabilities:      []float64{1},
		Texts:              []string{"普通文本"},
		TextRandomMode:     "integer",
		TextRandomIntRange: []int{42, 42},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(action.TextValues) != 1 || action.TextValues[0] != "42" {
		t.Fatalf("text values = %#v", action.TextValues)
	}
}

func TestBuildActionsWithLogicSkipsHiddenQuestion(t *testing.T) {
	q1 := 1
	q2 := 2
	q3 := 3
	actions, err := BuildActionsWithLogic([]model.QuestionMeta{
		{Num: 1, ProviderType: "single", TypeCode: "3", Options: 2, LogicStatus: model.LogicParseStatusNone},
		{
			Num:                 2,
			ProviderType:        "single",
			TypeCode:            "3",
			Options:             2,
			HasDisplayCondition: true,
			DisplayConditions: []map[string]any{{
				"condition_question_num":   1,
				"condition_mode":           "not_selected",
				"condition_option_indices": []any{0},
			}},
			LogicStatus: model.LogicParseStatusComplete,
		},
		{Num: 3, ProviderType: "single", TypeCode: "3", Options: 2, LogicStatus: model.LogicParseStatusNone},
	}, []model.QuestionEntry{
		{QuestionType: "single", QuestionNum: &q1, Probabilities: []float64{1, 0}},
		{QuestionType: "single", QuestionNum: &q2, Probabilities: []float64{1, 0}},
		{QuestionType: "single", QuestionNum: &q3, Probabilities: []float64{1, 0}},
	}, BuildOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if len(actions) != 2 || actions[0].QuestionNum != 1 || actions[1].QuestionNum != 3 {
		t.Fatalf("actions = %#v", actions)
	}
}

func TestBuildActionsWithLogicJumpTerminatesEarly(t *testing.T) {
	q1 := 1
	q2 := 2
	actions, err := BuildActionsWithLogic([]model.QuestionMeta{
		{
			Num:          1,
			ProviderType: "single",
			TypeCode:     "3",
			Options:      2,
			HasJump:      true,
			JumpRules: []map[string]any{{
				"option_index": 0,
				"jumpto":       3,
			}},
			LogicStatus: model.LogicParseStatusComplete,
		},
		{Num: 2, ProviderType: "single", TypeCode: "3", Options: 2, LogicStatus: model.LogicParseStatusNone},
	}, []model.QuestionEntry{
		{QuestionType: "single", QuestionNum: &q1, Probabilities: []float64{1, 0}},
		{QuestionType: "single", QuestionNum: &q2, Probabilities: []float64{1, 0}},
	}, BuildOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if len(actions) != 1 || actions[0].QuestionNum != 1 {
		t.Fatalf("actions = %#v", actions)
	}
}

func TestBuildActionsWithLogicRejectsUnknownJump(t *testing.T) {
	_, err := BuildActionsWithLogic([]model.QuestionMeta{{
		Num:         1,
		HasJump:     true,
		LogicStatus: model.LogicParseStatusUnknown,
	}}, nil, BuildOptions{})
	if err == nil || !strings.Contains(err.Error(), "逻辑规则未完整解析") {
		t.Fatalf("err = %v", err)
	}
}
