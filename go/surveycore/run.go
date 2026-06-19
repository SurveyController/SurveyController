package surveycore

import (
	"context"
	"fmt"
	"strings"
	"time"

	"surveycontroller/surveycore/credamo"
	"surveycontroller/surveycore/internal/model"
)

type EventHandler func(Event)

func (c *Client) Run(ctx context.Context, cfg *RuntimeConfig) (*RunResult, error) {
	return c.RunWithEvents(ctx, cfg, nil)
}

func (c *Client) RunWithEvents(ctx context.Context, cfg *RuntimeConfig, handler EventHandler) (*RunResult, error) {
	if cfg == nil {
		return nil, fmt.Errorf("%w: 配置为空", ErrInvalidConfig)
	}
	if strings.TrimSpace(cfg.URL) == "" {
		return nil, fmt.Errorf("%w: 必须提供问卷链接", ErrInvalidConfig)
	}
	if detectProvider(cfg.URL) != model.ProviderCredamo {
		return nil, fmt.Errorf("%w: only credamo run is supported", ErrUnsupportedOperation)
	}
	if cfg.SurveyProvider != "" && cfg.SurveyProvider != model.ProviderCredamo {
		return nil, fmt.Errorf("%w: only credamo run is supported", ErrUnsupportedOperation)
	}
	runner := credamo.Runner{HTTP: httpClientOrDefault(c.httpClient)}
	result, err := runner.Run(ctx, cfg, func(event credamo.Event) {
		if handler == nil {
			return
		}
		handler(Event{
			Worker:  event.Worker,
			Message: event.Message,
			Success: event.Success,
			Fail:    event.Fail,
			Current: event.Current,
			Total:   event.Total,
			Time:    event.Time,
		})
	})
	if err != nil {
		return resultFromCredamo(result), wrapRunError(err)
	}
	return resultFromCredamo(result), nil
}

func resultFromCredamo(result credamo.Result) *RunResult {
	progress := ThreadProgress{
		ThreadName:   "Worker-1",
		ThreadIndex:  0,
		SuccessCount: result.Success,
		FailCount:    result.Fail,
		StepCurrent:  result.Success + result.Fail,
		StepTotal:    result.Target,
		StatusText:   result.Status,
		Running:      false,
		LastUpdate:   time.Now(),
	}
	return &RunResult{
		Success:        result.Success,
		Fail:           result.Fail,
		Stopped:        false,
		ThreadProgress: []ThreadProgress{progress},
	}
}

func wrapRunError(err error) error {
	if err == nil {
		return nil
	}
	message := err.Error()
	switch {
	case strings.Contains(message, "解析"):
		return fmt.Errorf("%w: %v", ErrParseFailed, err)
	case strings.Contains(message, "配置") || strings.Contains(message, "答案"):
		return fmt.Errorf("%w: %v", ErrPrepareConfigFailed, err)
	default:
		return fmt.Errorf("%w: %v", ErrRunFailed, err)
	}
}
