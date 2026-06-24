package surveycore

import "surveycontroller/surveycore/internal/model"

func cloneRuntimeConfig(cfg *RuntimeConfig) RuntimeConfig {
	if cfg == nil {
		return RuntimeConfig{}
	}
	cloned := *cfg
	if cfg.ProxyAreaCode != nil {
		value := *cfg.ProxyAreaCode
		cloned.ProxyAreaCode = &value
	}
	cloned.RandomUARatios = cloneIntMap(cfg.RandomUARatios)
	cloned.AnswerRules = cloneRules(cfg.AnswerRules)
	cloned.DimensionGroups = append([]string(nil), cfg.DimensionGroups...)
	cloned.QuestionEntries = cloneQuestionEntries(cfg.QuestionEntries)
	cloned.QuestionsInfo = cloneQuestions(cfg.QuestionsInfo)
	cloned.Persona = clonePersona(cfg.Persona)
	return cloned
}

func clonePersona(src *model.Persona) *model.Persona {
	if src == nil {
		return nil
	}
	cloned := *src
	return &cloned
}

func cloneIntMap(src map[string]int) map[string]int {
	if len(src) == 0 {
		return nil
	}
	dst := make(map[string]int, len(src))
	for key, value := range src {
		dst[key] = value
	}
	return dst
}

func cloneRules(src []map[string]any) []map[string]any {
	if len(src) == 0 {
		return nil
	}
	dst := make([]map[string]any, len(src))
	for i, item := range src {
		if item == nil {
			continue
		}
		cloned := make(map[string]any, len(item))
		for key, value := range item {
			cloned[key] = value
		}
		dst[i] = cloned
	}
	return dst
}

func cloneQuestionEntries(src []QuestionEntry) []QuestionEntry {
	if len(src) == 0 {
		return nil
	}
	dst := make([]QuestionEntry, len(src))
	copy(dst, src)
	for i := range dst {
		dst[i].Probabilities = cloneAnySlice(src[i].Probabilities)
		dst[i].Texts = append([]string(nil), src[i].Texts...)
		dst[i].FillableOptionIndices = append([]int(nil), src[i].FillableOptionIndices...)
		dst[i].OptionFillTexts = append([]*string(nil), src[i].OptionFillTexts...)
		dst[i].AttachedOptionSelects = cloneMapList(src[i].AttachedOptionSelects)
		dst[i].LocationParts = append([]string(nil), src[i].LocationParts...)
		dst[i].MultiTextBlankModes = append([]string(nil), src[i].MultiTextBlankModes...)
		dst[i].MultiTextBlankAIFlags = append([]bool(nil), src[i].MultiTextBlankAIFlags...)
		dst[i].MultiTextBlankIntRanges = cloneIntRanges(src[i].MultiTextBlankIntRanges)
		dst[i].TextRandomIntRange = append([]int(nil), src[i].TextRandomIntRange...)
	}
	return dst
}

func cloneAnySlice(value any) any {
	switch typed := value.(type) {
	case []float64:
		return append([]float64(nil), typed...)
	case [][]float64:
		cloned := make([][]float64, len(typed))
		for i := range typed {
			cloned[i] = append([]float64(nil), typed[i]...)
		}
		return cloned
	case []int:
		return append([]int(nil), typed...)
	case [][]int:
		cloned := make([][]int, len(typed))
		for i := range typed {
			cloned[i] = append([]int(nil), typed[i]...)
		}
		return cloned
	case []any:
		cloned := make([]any, len(typed))
		for i := range typed {
			cloned[i] = cloneAnySlice(typed[i])
		}
		return cloned
	default:
		return value
	}
}

func cloneMapList(src []map[string]any) []map[string]any {
	if len(src) == 0 {
		return nil
	}
	dst := make([]map[string]any, len(src))
	for i, item := range src {
		if item == nil {
			continue
		}
		cloned := make(map[string]any, len(item))
		for key, value := range item {
			cloned[key] = value
		}
		dst[i] = cloned
	}
	return dst
}

func cloneIntRanges(src [][]int) [][]int {
	if len(src) == 0 {
		return nil
	}
	dst := make([][]int, len(src))
	for i, item := range src {
		dst[i] = append([]int(nil), item...)
	}
	return dst
}
