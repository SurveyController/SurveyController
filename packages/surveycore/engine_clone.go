package surveycore

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
	return cloned
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
