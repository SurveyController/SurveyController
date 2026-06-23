package surveycore

import (
	"context"
	"fmt"
	"strings"
	"time"

	"surveycontroller/surveycore/credamo"
	"surveycontroller/surveycore/internal/model"
	"surveycontroller/surveycore/tencent"
	"surveycontroller/surveycore/wjx"
)

type EventHandler func(Event)

func (c *Client) Run(ctx context.Context, cfg *RuntimeConfig) (*RunResult, error) {
	return c.RunWithEvents(ctx, cfg, nil)
}

func (c *Client) RunWithEvents(ctx context.Context, cfg *RuntimeConfig, handler EventHandler) (*RunResult, error) {
	return c.RunWithExecutionOptions(ctx, cfg, handler, ExecutionOptionsFromConfig(cfg))
}

func (c *Client) RunWithExecutionOptions(ctx context.Context, cfg *RuntimeConfig, handler EventHandler, options ExecutionOptions) (*RunResult, error) {
	if cfg == nil {
		return nil, fmt.Errorf("%w: 配置为空", ErrInvalidConfig)
	}
	if strings.TrimSpace(cfg.URL) == "" {
		return nil, fmt.Errorf("%w: 必须提供问卷链接", ErrInvalidConfig)
	}
	provider := detectProvider(cfg.URL)
	if cfg.SurveyProvider != "" {
		provider = cfg.SurveyProvider
	}
	if provider == model.ProviderQQ {
		runner := tencent.Runner{HTTP: httpClientOrDefault(c.httpClient)}
		result, err := RunExecution(ctx, cfg, func(runCtx context.Context, local *RuntimeConfig, localHandler EventHandler) (*RunResult, error) {
			runResult, runErr := runner.Run(runCtx, local, func(event tencent.Event) {
				if localHandler == nil {
					return
				}
				localHandler(Event{
					Worker:  event.Worker,
					Message: event.Message,
					Success: event.Success,
					Fail:    event.Fail,
					Current: event.Current,
					Total:   event.Total,
					Time:    event.Time,
				})
			})
			return resultFromTencent(runResult), runErr
		}, handler, options)
		if err != nil {
			return result, wrapRunError(err)
		}
		return result, nil
	}
	if provider == model.ProviderWJX {
		runner := wjx.Runner{Client: c.httpClient.Client}
		result, err := RunExecution(ctx, cfg, func(runCtx context.Context, local *RuntimeConfig, localHandler EventHandler) (*RunResult, error) {
			runResult, runErr := runner.Run(runCtx, local, func(event wjx.Event) {
				if localHandler == nil {
					return
				}
				localHandler(Event{
					Worker:  event.Worker,
					Message: event.Message,
					Success: event.Success,
					Fail:    event.Fail,
					Current: event.Current,
					Total:   event.Total,
					Time:    event.Time,
				})
			})
			return resultFromWJX(runResult), runErr
		}, handler, options)
		if err != nil {
			return result, wrapRunError(err)
		}
		return result, nil
	}
	if provider != model.ProviderCredamo {
		return nil, fmt.Errorf("%w: only credamo run is supported", ErrUnsupportedOperation)
	}
	runner := credamo.Runner{HTTP: httpClientOrDefault(c.httpClient)}
	result, err := RunExecution(ctx, cfg, func(runCtx context.Context, local *RuntimeConfig, localHandler EventHandler) (*RunResult, error) {
		runResult, runErr := runner.Run(runCtx, local, func(event credamo.Event) {
			if localHandler == nil {
				return
			}
			localHandler(Event{
				Worker:  event.Worker,
				Message: event.Message,
				Success: event.Success,
				Fail:    event.Fail,
				Current: event.Current,
				Total:   event.Total,
				Time:    event.Time,
			})
		})
		return resultFromCredamo(runResult), runErr
	}, handler, options)
	if err != nil {
		return result, wrapRunError(err)
	}
	return result, nil
}

func ExecutionOptionsFromConfig(cfg *RuntimeConfig) ExecutionOptions {
	if cfg == nil {
		return ExecutionOptions{}
	}
	target := cfg.Target
	if target <= 0 {
		target = 1
	}
	threads := cfg.Threads
	if threads <= 0 {
		threads = 1
	}
	maxRetries := 0
	if cfg.ReliabilityModeEnabled {
		maxRetries = 1
	}
	return ExecutionOptions{
		Target:          target,
		Threads:         threads,
		MaxRetries:      maxRetries,
		FailStop:        cfg.FailStopEnabled,
		CooldownOnError: 30 * time.Second,
	}
}

func resultFromTencent(result tencent.Result) *RunResult {
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
		Stopped:        result.Status == "stopped",
		ThreadProgress: []ThreadProgress{progress},
	}
}

func resultFromWJX(result wjx.Result) *RunResult {
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
		Stopped:        result.Status == "stopped",
		ThreadProgress: []ThreadProgress{progress},
	}
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
