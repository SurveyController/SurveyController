package answerplan

import "surveycontroller/surveycore/internal/model"

type BuildOptions struct {
	AnswerRules    []map[string]any
	Runtime        model.AnswerRuntime
	RuntimeOwner   string
	Persona        *model.Persona
	DimensionBases map[string]float64
}

func OptionsFromRuntimeConfig(cfg *model.RuntimeConfig) BuildOptions {
	if cfg == nil {
		return BuildOptions{}
	}
	return BuildOptions{
		AnswerRules:    cfg.AnswerRules,
		Runtime:        cfg.AnswerRuntime,
		RuntimeOwner:   cfg.AnswerRuntimeOwner,
		Persona:        cfg.Persona,
		DimensionBases: map[string]float64{},
	}
}

func BuildActions(questions []model.QuestionMeta, entries []model.QuestionEntry, options BuildOptions) ([]Action, error) {
	index := NewEntryIndex(entries)
	consistency := newConsistencyPlan(options.AnswerRules)
	actions := make([]Action, 0, len(questions))
	for _, question := range questions {
		if question.IsDescription {
			continue
		}
		entry, ok := index.Find(question)
		if !ok {
			entry = DefaultEntry(question)
		}
		entry = consistency.apply(question, entry)
		action, err := BuildActionWithOptions(question, entry, options)
		if err != nil {
			return nil, err
		}
		actions = append(actions, action)
		consistency.record(action)
	}
	return actions, nil
}

func DefaultEntry(question model.QuestionMeta) model.QuestionEntry {
	num := question.Num
	providerID := question.ProviderID
	return model.QuestionEntry{
		QuestionType:       defaultQuestionType(question),
		Probabilities:      defaultProbabilities(question),
		Rows:               question.Rows,
		OptionCount:        maxInt(1, question.Options),
		QuestionNum:        &num,
		ProviderQuestionID: &providerID,
		SurveyProvider:     question.Provider,
	}
}

func defaultQuestionType(question model.QuestionMeta) string {
	switch question.ProviderType {
	case "single", "multiple", "dropdown", "scale", "matrix", "order", "slider", "text", "multi_text":
		if question.ProviderType == "multi_text" {
			return "text"
		}
		return question.ProviderType
	case "radio":
		return "single"
	case "checkbox":
		return "multiple"
	case "select":
		return "dropdown"
	case "matrix_radio":
		return "matrix"
	case "textarea":
		return "text"
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
	case "8":
		return "slider"
	case "11":
		return "order"
	default:
		return "text"
	}
}

func defaultProbabilities(question model.QuestionMeta) []float64 {
	count := maxInt(1, question.Options)
	values := make([]float64, count)
	kind := defaultQuestionType(question)
	for i := range values {
		if kind == "multiple" {
			values[i] = 50
		} else {
			values[i] = 1
		}
	}
	return values
}
