package surveycore

import (
	"context"
	"fmt"

	"surveycontroller/surveycore/internal/psychometrics"
)

func (c *Client) preparePsychometricExecution(ctx context.Context, cfg *RuntimeConfig, options ExecutionOptions) (*RuntimeConfig, ExecutionOptions, error) {
	if cfg == nil {
		return nil, options, fmt.Errorf("%w: 配置为空", ErrInvalidConfig)
	}
	runCfg := cloneRuntimeConfig(cfg)
	if runCfg.ReverseFillEnabled || !runCfg.ReliabilityModeEnabled {
		return &runCfg, options, nil
	}
	if len(runCfg.QuestionsInfo) == 0 {
		definition, err := c.Parse(ctx, runCfg.URL)
		if err != nil {
			return nil, options, fmt.Errorf("%w: 信效度计划需要先解析问卷: %v", ErrParseFailed, err)
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
	runCfg.Target = target
	plan := psychometrics.BuildJointPlan(&runCfg)
	if plan == nil {
		return &runCfg, options, nil
	}
	configure := options.ConfigureRun
	options.ConfigureRun = func(ctx context.Context, jobIndex int, attempt int, local *RuntimeConfig) error {
		if configure != nil {
			if err := configure(ctx, jobIndex, attempt, local); err != nil {
				return err
			}
		}
		if jobIndex < 0 || jobIndex >= plan.SampleCount {
			return fmt.Errorf("%w: 信效度样本序号超出范围", ErrPrepareConfigFailed)
		}
		local.QuestionEntries = psychometrics.ApplySample(local.QuestionEntries, local.QuestionsInfo, plan, jobIndex)
		return nil
	}
	return &runCfg, options, nil
}
