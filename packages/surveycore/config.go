package surveycore

import (
	"context"
	"strings"

	"surveycontroller/surveycore/internal/model"
)

func (c *Client) DefaultConfig(ctx context.Context, surveyURL string) (*RuntimeConfig, error) {
	cfg := newDefaultRuntimeConfig()
	cfg.URL = strings.TrimSpace(surveyURL)
	if cfg.URL == "" {
		return &cfg, nil
	}
	definition, err := c.Parse(ctx, cfg.URL)
	if err != nil {
		return nil, err
	}
	cfg.SurveyTitle = definition.Title
	cfg.SurveyProvider = definition.Provider
	cfg.QuestionsInfo = cloneQuestions(definition.Questions)
	cfg.QuestionEntries = buildDefaultQuestionEntries(definition.Questions)
	return &cfg, nil
}

func newDefaultRuntimeConfig() RuntimeConfig {
	return RuntimeConfig{
		SurveyProvider:         model.ProviderWJX,
		Target:                 1,
		Threads:                1,
		SubmitInterval:         [2]int{0, 0},
		AnswerDuration:         [2]int{60, 120},
		ProxySource:            "default",
		RandomUARatios:         map[string]int{"wechat": 33, "mobile": 33, "pc": 34},
		FailStopEnabled:        true,
		PauseOnAliyunCaptcha:   true,
		ReliabilityModeEnabled: true,
		PsychoTargetAlpha:      0.85,
		AIMode:                 "free",
		AIProvider:             "deepseek",
		AIAPIProtocol:          "auto",
		ReverseFillFormat:      "auto",
		ReverseFillStartRow:    1,
		ReverseFillThreads:     1,
		AnswerRules:            []map[string]any{},
		DimensionGroups:        []string{},
	}
}

func cloneQuestions(src []QuestionMeta) []QuestionMeta {
	cloned := make([]QuestionMeta, len(src))
	copy(cloned, src)
	for i := range cloned {
		cloned[i].RowTexts = append([]string(nil), src[i].RowTexts...)
		cloned[i].OptionTexts = append([]string(nil), src[i].OptionTexts...)
		cloned[i].TextInputLabels = append([]string(nil), src[i].TextInputLabels...)
		cloned[i].JumpRules = cloneMapList(src[i].JumpRules)
		cloned[i].DisplayConditions = cloneMapList(src[i].DisplayConditions)
		cloned[i].ControlsDisplayTargets = cloneMapList(src[i].ControlsDisplayTargets)
		cloned[i].QuestionMedia = cloneMapList(src[i].QuestionMedia)
		cloned[i].ForcedTexts = append([]string(nil), src[i].ForcedTexts...)
		cloned[i].FillableOptions = append([]int(nil), src[i].FillableOptions...)
		cloned[i].AttachedOptionSelects = cloneMapList(src[i].AttachedOptionSelects)
	}
	return cloned
}

func buildDefaultQuestionEntries(questions []QuestionMeta) []QuestionEntry {
	entries := make([]QuestionEntry, 0, len(questions))
	for _, question := range questions {
		if question.IsDescription {
			continue
		}
		num := question.Num
		title := question.Title
		providerID := question.ProviderID
		pageID := question.ProviderPageID
		entry := QuestionEntry{
			QuestionType:          questionTypeName(question),
			Probabilities:         defaultProbabilities(question),
			Rows:                  question.Rows,
			OptionCount:           maxInt(1, question.Options),
			DistributionMode:      "random",
			QuestionNum:           &num,
			QuestionTitle:         &title,
			SurveyProvider:        question.Provider,
			ProviderQuestionID:    &providerID,
			ProviderPageID:        &pageID,
			FillableOptionIndices: append([]int(nil), question.FillableOptions...),
			AttachedOptionSelects: cloneMapList(question.AttachedOptionSelects),
			IsLocation:            question.IsLocation,
			PsychoBias:            "custom",
		}
		if len(question.ForcedTexts) > 0 {
			entry.Texts = append([]string(nil), question.ForcedTexts...)
		}
		entries = append(entries, entry)
	}
	return entries
}

func questionTypeName(question QuestionMeta) string {
	if question.ProviderType != "" {
		switch question.ProviderType {
		case "single", "multiple", "dropdown", "scale", "matrix", "order", "text":
			return question.ProviderType
		case "multi_text":
			return "text"
		}
	}
	switch question.TypeCode {
	case "3":
		return "single"
	case "4":
		return "multiple"
	case "5":
		return "scale"
	case "6":
		return "matrix"
	case "7":
		return "dropdown"
	case "11":
		return "order"
	default:
		if question.IsTextLike || question.TextInputs > 0 {
			return "text"
		}
		return "text"
	}
}

func defaultProbabilities(question QuestionMeta) any {
	if question.ForcedOptionIdx != nil && question.Options > 0 {
		values := make([]float64, question.Options)
		if *question.ForcedOptionIdx >= 0 && *question.ForcedOptionIdx < len(values) {
			values[*question.ForcedOptionIdx] = 1
			return values
		}
	}
	switch questionTypeName(question) {
	case "single", "dropdown", "scale":
		values := make([]float64, question.Options)
		for i := range values {
			values[i] = 1
		}
		return values
	case "multiple", "order":
		values := make([]float64, question.Options)
		for i := range values {
			if questionTypeName(question) == "multiple" {
				values[i] = 50
			} else {
				values[i] = 1
			}
		}
		return values
	case "matrix":
		values := make([]float64, question.Options)
		for i := range values {
			values[i] = 1
		}
		return values
	case "text":
		if len(question.ForcedTexts) > 0 {
			return []float64{1}
		}
		return []float64{1}
	}
	return -1
}

func maxInt(left int, right int) int {
	if left > right {
		return left
	}
	return right
}
