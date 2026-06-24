package surveycore

import (
	"context"
	"fmt"
	"strings"

	"surveycontroller/surveycore/internal/model"
	"surveycontroller/surveycore/reversefill"
)

func (c *Client) prepareReverseFillExecution(ctx context.Context, cfg *RuntimeConfig, provider string, options ExecutionOptions) (*RuntimeConfig, ExecutionOptions, error) {
	if cfg == nil {
		return nil, options, fmt.Errorf("%w: 配置为空", ErrInvalidConfig)
	}
	runCfg := cloneRuntimeConfig(cfg)
	if !runCfg.ReverseFillEnabled || strings.TrimSpace(runCfg.ReverseFillSourcePath) == "" {
		return &runCfg, options, nil
	}
	if provider != model.ProviderWJX {
		return nil, options, fmt.Errorf("%w: 反填 V1 目前只支持问卷星", ErrUnsupportedOperation)
	}
	if len(runCfg.QuestionsInfo) == 0 {
		definition, err := c.Parse(ctx, runCfg.URL)
		if err != nil {
			return nil, options, fmt.Errorf("%w: 反填需要先解析问卷: %v", ErrParseFailed, err)
		}
		runCfg.SurveyTitle = definition.Title
		runCfg.SurveyProvider = definition.Provider
		runCfg.QuestionsInfo = cloneQuestions(definition.Questions)
		if len(runCfg.QuestionEntries) == 0 {
			runCfg.QuestionEntries = buildDefaultQuestionEntries(definition.Questions)
		}
	}
	if len(runCfg.QuestionEntries) == 0 {
		runCfg.QuestionEntries = buildDefaultQuestionEntries(runCfg.QuestionsInfo)
	}

	target := options.Target
	if target <= 0 {
		target = runCfg.Target
	}
	if target <= 0 {
		target = 1
	}
	preview, err := reversefill.PreviewExcel(reversefill.PreviewOptions{
		Path:          runCfg.ReverseFillSourcePath,
		Format:        runCfg.ReverseFillFormat,
		StartRow:      runCfg.ReverseFillStartRow,
		Questions:     runCfg.QuestionsInfo,
		MaxSampleRows: target,
	})
	if err != nil {
		return nil, options, fmt.Errorf("%w: 反填样本读取失败: %v", ErrPrepareConfigFailed, err)
	}
	if preview.TotalDataRows <= 0 {
		return nil, options, fmt.Errorf("%w: 反填起始行后没有可用样本", ErrPrepareConfigFailed)
	}
	if target > preview.TotalDataRows {
		return nil, options, fmt.Errorf("%w: 反填目标份数为 %d，但可用样本只有 %d 行", ErrPrepareConfigFailed, target, preview.TotalDataRows)
	}
	if len(preview.UnsupportedFields) > 0 {
		return nil, options, fmt.Errorf("%w: %s", ErrPrepareConfigFailed, preview.UnsupportedFields[0])
	}
	if len(preview.SampleRows) < target {
		return nil, options, fmt.Errorf("%w: 反填样本中可回放行数不足，目标 %d 行，可回放 %d 行", ErrPrepareConfigFailed, target, len(preview.SampleRows))
	}

	samples := append([]reversefill.SampleRow(nil), preview.SampleRows...)
	if runCfg.ReverseFillThreads > 0 {
		options.Threads = runCfg.ReverseFillThreads
		runCfg.Threads = runCfg.ReverseFillThreads
	}
	options.Target = target
	runCfg.Target = target

	configure := options.ConfigureRun
	options.ConfigureRun = func(ctx context.Context, jobIndex int, attempt int, local *RuntimeConfig) error {
		if configure != nil {
			if err := configure(ctx, jobIndex, attempt, local); err != nil {
				return err
			}
		}
		if jobIndex < 0 || jobIndex >= len(samples) {
			return fmt.Errorf("%w: 反填任务序号超出样本范围", ErrPrepareConfigFailed)
		}
		entries, err := applyReverseFillSample(local.QuestionEntries, local.QuestionsInfo, samples[jobIndex])
		if err != nil {
			return err
		}
		local.QuestionEntries = entries
		return nil
	}
	return &runCfg, options, nil
}

func applyReverseFillSample(entries []QuestionEntry, questions []QuestionMeta, sample reversefill.SampleRow) ([]QuestionEntry, error) {
	cloned := cloneQuestionEntries(entries)
	questionByNum := map[int]QuestionMeta{}
	for _, question := range questions {
		questionByNum[question.Num] = question
	}
	entryIndex := map[int]int{}
	for index, entry := range cloned {
		if entry.QuestionNum != nil {
			entryIndex[*entry.QuestionNum] = index
		}
	}
	for questionNum, answer := range sample.Answers {
		question, ok := questionByNum[questionNum]
		if !ok {
			continue
		}
		index, ok := entryIndex[questionNum]
		if !ok {
			defaults := buildDefaultQuestionEntries([]QuestionMeta{question})
			if len(defaults) == 0 {
				continue
			}
			cloned = append(cloned, defaults[0])
			index = len(cloned) - 1
			entryIndex[questionNum] = index
		}
		entry := cloned[index]
		if err := applyReverseFillAnswer(&entry, question, answer); err != nil {
			return nil, err
		}
		cloned[index] = entry
	}
	return cloned, nil
}

func applyReverseFillAnswer(entry *QuestionEntry, question QuestionMeta, answer reversefill.Answer) error {
	if entry.QuestionNum == nil {
		num := question.Num
		entry.QuestionNum = &num
	}
	if entry.ProviderQuestionID == nil && strings.TrimSpace(question.ProviderID) != "" {
		providerID := question.ProviderID
		entry.ProviderQuestionID = &providerID
	}
	entry.SurveyProvider = question.Provider
	entry.DistributionMode = "reverse_fill"

	switch answer.Kind {
	case reversefill.KindChoice:
		if answer.ChoiceIndex == nil {
			return fmt.Errorf("%w: 第%d题反填选项为空", ErrPrepareConfigFailed, question.Num)
		}
		values, err := oneHotProbabilities(question.Num, optionCountForReverseFill(question, *entry), *answer.ChoiceIndex)
		if err != nil {
			return err
		}
		entry.QuestionType = questionTypeName(question)
		entry.OptionCount = len(values)
		entry.Probabilities = values
	case reversefill.KindText:
		entry.QuestionType = "text"
		entry.Texts = []string{strings.TrimSpace(answer.TextValue)}
		entry.Probabilities = []float64{1}
	case reversefill.KindMultiText:
		entry.QuestionType = "text"
		entry.Texts = append([]string(nil), answer.TextValues...)
		entry.Probabilities = []float64{1}
	case reversefill.KindMatrix:
		values, err := matrixProbabilities(question, *entry, answer.MatrixChoiceIndexes)
		if err != nil {
			return err
		}
		entry.QuestionType = "matrix"
		entry.Rows = len(values)
		if len(values) > 0 {
			entry.OptionCount = len(values[0])
		}
		entry.Probabilities = values
	default:
		return fmt.Errorf("%w: 第%d题反填类型不支持：%s", ErrPrepareConfigFailed, question.Num, answer.Kind)
	}
	return nil
}

func optionCountForReverseFill(question QuestionMeta, entry QuestionEntry) int {
	if question.Options > 0 {
		return question.Options
	}
	if entry.OptionCount > 0 {
		return entry.OptionCount
	}
	if values := probabilityValues(entry.Probabilities); len(values) > 0 {
		return len(values)
	}
	return 1
}

func matrixProbabilities(question QuestionMeta, entry QuestionEntry, indexes []int) ([][]float64, error) {
	rows := question.Rows
	if rows <= 0 {
		rows = entry.Rows
	}
	if rows <= 0 {
		rows = len(indexes)
	}
	if rows <= 0 {
		rows = 1
	}
	if len(indexes) != rows {
		return nil, fmt.Errorf("%w: 第%d题矩阵反填行数为 %d，题目行数为 %d", ErrPrepareConfigFailed, question.Num, len(indexes), rows)
	}
	optionCount := optionCountForReverseFill(question, entry)
	result := make([][]float64, 0, rows)
	for _, index := range indexes {
		values, err := oneHotProbabilities(question.Num, optionCount, index)
		if err != nil {
			return nil, err
		}
		result = append(result, values)
	}
	return result, nil
}

func oneHotProbabilities(questionNum int, count int, index int) ([]float64, error) {
	if count <= 0 {
		count = 1
	}
	if index < 0 || index >= count {
		return nil, fmt.Errorf("%w: 第%d题选项序号 %d 超出范围", ErrPrepareConfigFailed, questionNum, index+1)
	}
	values := make([]float64, count)
	values[index] = 1
	return values, nil
}

func probabilityValues(raw any) []float64 {
	switch values := raw.(type) {
	case []float64:
		return append([]float64(nil), values...)
	case []int:
		result := make([]float64, 0, len(values))
		for _, value := range values {
			result = append(result, float64(value))
		}
		return result
	default:
		return nil
	}
}
