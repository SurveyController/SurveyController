package surveycore

import (
	"fmt"
	"strings"

	"surveycontroller/surveycore/internal/model"
)

func prepareAnswerDatetimeWindowExecution(cfg *RuntimeConfig, provider string) error {
	if cfg == nil {
		return fmt.Errorf("%w: 配置为空", ErrInvalidConfig)
	}
	cfg.AnswerDatetimeWindow = model.NormalizeAnswerDatetimeWindow(cfg.AnswerDatetimeWindow)
	if !supportsAnswerDatetimeWindow(provider) {
		return nil
	}
	startText, endText := cfg.AnswerDatetimeWindow[0], cfg.AnswerDatetimeWindow[1]
	if startText == "" && endText == "" {
		return nil
	}
	if startText == "" || endText == "" {
		return fmt.Errorf("%w: 见数作答时间窗未配完整，请先设置开始和结束日期时间", ErrPrepareConfigFailed)
	}
	start, startOK := model.ParseAnswerDatetimeString(startText)
	end, endOK := model.ParseAnswerDatetimeString(endText)
	if !startOK || !endOK {
		return fmt.Errorf("%w: 见数作答时间窗格式无效，请重新选择日期时间", ErrPrepareConfigFailed)
	}
	if !end.After(start) {
		return fmt.Errorf("%w: 见数结束日期时间必须晚于开始日期时间", ErrPrepareConfigFailed)
	}
	maxDurationSeconds := cfg.AnswerDuration[1]
	if maxDurationSeconds < 0 {
		maxDurationSeconds = 0
	}
	if int(end.Sub(start).Seconds()) < maxDurationSeconds {
		return fmt.Errorf("%w: 见数作答时间窗太窄，容不下当前最长作答时长", ErrPrepareConfigFailed)
	}
	return nil
}

func supportsAnswerDatetimeWindow(provider string) bool {
	return strings.ToLower(strings.TrimSpace(provider)) == model.ProviderCredamo
}
