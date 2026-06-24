package surveycore

import (
	"context"
	"strings"
	"testing"

	"surveycontroller/surveycore/internal/model"
)

func TestPrepareAIExecutionAppliesTextAnswers(t *testing.T) {
	questionNum := 1
	title := "意见"
	client := New(WithAITextResolver(AITextResolverFunc(func(_ context.Context, _ RuntimeConfig, request AITextRequest) ([]string, error) {
		if request.QuestionNum != 1 || request.BlankCount != 2 {
			t.Fatalf("request = %#v", request)
		}
		return []string{"第一空", "第二空"}, nil
	})))
	cfg := RuntimeConfig{
		URL: "https://www.wjx.cn/vm/demo.aspx",
		QuestionsInfo: []QuestionMeta{{
			Num:          1,
			Provider:     model.ProviderWJX,
			ProviderType: "text",
			Title:        title,
			TextInputs:   2,
		}},
		QuestionEntries: []QuestionEntry{{
			QuestionType:  "text",
			QuestionNum:   &questionNum,
			QuestionTitle: &title,
			AIEnabled:     true,
		}},
	}
	runCfg, options, err := client.prepareAIExecution(context.Background(), &cfg, ExecutionOptions{})
	if err != nil {
		t.Fatal(err)
	}
	local := cloneRuntimeConfig(runCfg)
	if options.ConfigureRun == nil {
		t.Fatal("ConfigureRun is nil")
	}
	if err := options.ConfigureRun(context.Background(), 0, 1, &local); err != nil {
		t.Fatal(err)
	}
	if got := local.QuestionEntries[0].Texts; len(got) != 2 || got[0] != "第一空" || got[1] != "第二空" {
		t.Fatalf("texts = %#v", got)
	}
}

func TestPrepareAIExecutionResolvesOptionFillToken(t *testing.T) {
	questionNum := 1
	token := optionFillAIToken
	client := New(WithAITextResolver(AITextResolverFunc(func(_ context.Context, _ RuntimeConfig, request AITextRequest) ([]string, error) {
		if request.QuestionNum != 1 || !strings.Contains(request.Title, "其他") {
			t.Fatalf("request = %#v", request)
		}
		return []string{"AI 填写"}, nil
	})))
	cfg := RuntimeConfig{
		URL: "https://www.wjx.cn/vm/demo.aspx",
		QuestionsInfo: []QuestionMeta{{
			Num:          1,
			Provider:     model.ProviderWJX,
			ProviderType: "single",
			Title:        "职业",
			Options:      2,
			OptionTexts:  []string{"学生", "其他"},
		}},
		QuestionEntries: []QuestionEntry{{
			QuestionType:    "single",
			QuestionNum:     &questionNum,
			Probabilities:   []float64{0, 1},
			OptionFillTexts: []*string{nil, &token},
		}},
	}
	runCfg, options, err := client.prepareAIExecution(context.Background(), &cfg, ExecutionOptions{})
	if err != nil {
		t.Fatal(err)
	}
	local := cloneRuntimeConfig(runCfg)
	if err := options.ConfigureRun(context.Background(), 0, 1, &local); err != nil {
		t.Fatal(err)
	}
	if got := local.QuestionEntries[0].OptionFillTexts[1]; got == nil || *got != "AI 填写" {
		t.Fatalf("option fill = %#v", got)
	}
}

func TestAIQuestionPromptIncludesPersona(t *testing.T) {
	prompt := aiQuestionPrompt(RuntimeConfig{Persona: &model.Persona{Gender: "女", AgeGroup: "26-35"}}, AITextRequest{
		QuestionNum: 1,
		Title:       "你的看法",
		BlankCount:  1,
	})
	if !strings.Contains(prompt, "你扮演的角色是") || !strings.Contains(prompt, "26-35岁") {
		t.Fatalf("prompt = %q", prompt)
	}
}
