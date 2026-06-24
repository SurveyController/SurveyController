package surveycore

import (
	"context"
	"fmt"
	"strings"
)

func (c *Client) prepareAIExecution(ctx context.Context, cfg *RuntimeConfig, options ExecutionOptions) (*RuntimeConfig, ExecutionOptions, error) {
	if cfg == nil {
		return nil, options, fmt.Errorf("%w: 配置为空", ErrInvalidConfig)
	}
	runCfg := cloneRuntimeConfig(cfg)
	if runCfg.ReverseFillEnabled || !hasAIEntries(runCfg.QuestionEntries) {
		return &runCfg, options, nil
	}
	if len(runCfg.QuestionsInfo) == 0 {
		definition, err := c.Parse(ctx, runCfg.URL)
		if err != nil {
			return nil, options, fmt.Errorf("%w: AI 作答需要先解析问卷: %v", ErrParseFailed, err)
		}
		runCfg.SurveyTitle = definition.Title
		runCfg.SurveyProvider = definition.Provider
		runCfg.QuestionsInfo = cloneQuestions(definition.Questions)
		if len(runCfg.QuestionEntries) == 0 {
			runCfg.QuestionEntries = buildDefaultQuestionEntries(definition.Questions)
		}
	}
	configure := options.ConfigureRun
	options.ConfigureRun = func(ctx context.Context, jobIndex int, attempt int, local *RuntimeConfig) error {
		if configure != nil {
			if err := configure(ctx, jobIndex, attempt, local); err != nil {
				return err
			}
		}
		entries, err := c.applyAITextAnswers(ctx, *local)
		if err != nil {
			return err
		}
		local.QuestionEntries = entries
		return nil
	}
	return &runCfg, options, nil
}

func (c *Client) applyAITextAnswers(ctx context.Context, cfg RuntimeConfig) ([]QuestionEntry, error) {
	entries := cloneQuestionEntries(cfg.QuestionEntries)
	questions := map[int]QuestionMeta{}
	for _, question := range cfg.QuestionsInfo {
		questions[question.Num] = question
	}
	for index := range entries {
		entry := &entries[index]
		if !entryAIEnabled(*entry) {
			if err := c.applyAIOptionFillTexts(ctx, cfg, entry, questions, index); err != nil {
				return nil, err
			}
			continue
		}
		questionNum, question := resolveAIQuestion(*entry, questions, index)
		blankCount := textBlankCount(question, *entry)
		answers, err := c.resolveAIText(ctx, cfg, AITextRequest{
			QuestionNum: questionNum,
			Title:       firstText(question.Title, derefString(entry.QuestionTitle)),
			Description: question.Description,
			BlankCount:  blankCount,
		})
		if err != nil {
			return nil, fmt.Errorf("%w: 第%d题 AI 作答失败: %v", ErrPrepareConfigFailed, questionNum, err)
		}
		entry.QuestionType = "text"
		entry.Texts = answers
		entry.Probabilities = []float64{1}
		if err := c.applyAIOptionFillTexts(ctx, cfg, entry, questions, index); err != nil {
			return nil, err
		}
	}
	return entries, nil
}

func hasAIEntries(entries []QuestionEntry) bool {
	for _, entry := range entries {
		if entryAIEnabled(entry) || entryHasAIOptionFill(entry) {
			return true
		}
	}
	return false
}

func entryAIEnabled(entry QuestionEntry) bool {
	kind := strings.TrimSpace(entry.QuestionType)
	if kind != "text" && kind != "multi_text" {
		return false
	}
	if entry.AIEnabled {
		return true
	}
	if len(entry.MultiTextBlankAIFlags) == 0 {
		return false
	}
	for _, flag := range entry.MultiTextBlankAIFlags {
		if !flag {
			return false
		}
	}
	return true
}

func entryHasAIOptionFill(entry QuestionEntry) bool {
	for _, value := range entry.OptionFillTexts {
		if value != nil && strings.TrimSpace(*value) == optionFillAIToken {
			return true
		}
	}
	return false
}

func (c *Client) applyAIOptionFillTexts(ctx context.Context, cfg RuntimeConfig, entry *QuestionEntry, questions map[int]QuestionMeta, entryIndex int) error {
	if entry == nil || !entryHasAIOptionFill(*entry) {
		return nil
	}
	questionNum, question := resolveAIQuestion(*entry, questions, entryIndex)
	for optionIndex, value := range entry.OptionFillTexts {
		if value == nil || strings.TrimSpace(*value) != optionFillAIToken {
			continue
		}
		title := firstText(question.Title, derefString(entry.QuestionTitle), fmt.Sprintf("第%d题", questionNum))
		if optionIndex >= 0 && optionIndex < len(question.OptionTexts) {
			if optionText := strings.TrimSpace(question.OptionTexts[optionIndex]); optionText != "" {
				title += "\n选项：" + optionText
			}
		}
		answers, err := c.resolveAIText(ctx, cfg, AITextRequest{
			QuestionNum: questionNum,
			Title:       title,
			Description: question.Description,
			BlankCount:  1,
		})
		if err != nil {
			return fmt.Errorf("%w: 第%d题第%d个选项 AI 填空失败: %v", ErrPrepareConfigFailed, questionNum, optionIndex+1, err)
		}
		text := answers[0]
		entry.OptionFillTexts[optionIndex] = &text
	}
	return nil
}

func resolveAIQuestion(entry QuestionEntry, questions map[int]QuestionMeta, entryIndex int) (int, QuestionMeta) {
	questionNum := entryIndex + 1
	if entry.QuestionNum != nil && *entry.QuestionNum > 0 {
		questionNum = *entry.QuestionNum
	}
	question := questions[questionNum]
	if question.Num == 0 {
		question.Num = questionNum
		if entry.QuestionTitle != nil {
			question.Title = *entry.QuestionTitle
		}
		question.TextInputs = maxInt(1, len(entry.Texts))
	}
	return questionNum, question
}

func textBlankCount(question QuestionMeta, entry QuestionEntry) int {
	if question.TextInputs > 0 {
		return question.TextInputs
	}
	if len(entry.MultiTextBlankAIFlags) > 0 {
		return len(entry.MultiTextBlankAIFlags)
	}
	if len(entry.Texts) > 1 {
		return len(entry.Texts)
	}
	return 1
}

func derefString(value *string) string {
	if value == nil {
		return ""
	}
	return strings.TrimSpace(*value)
}

func firstText(values ...string) string {
	for _, value := range values {
		if text := strings.TrimSpace(value); text != "" {
			return text
		}
	}
	return ""
}
