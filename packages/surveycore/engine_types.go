package surveycore

import (
	"context"
	"errors"
	"strings"
	"time"
)

type ErrorKind string

const (
	ErrorKindCanceled    ErrorKind = "canceled"
	ErrorKindParse       ErrorKind = "parse"
	ErrorKindConfig      ErrorKind = "config"
	ErrorKindUnsupported ErrorKind = "unsupported"
	ErrorKindRun         ErrorKind = "run"
)

type ExecutionLease struct {
	Address string
	Source  string
}

type LeaseManager interface {
	Acquire(ctx context.Context, owner string) (ExecutionLease, error)
	Release(owner string) (ExecutionLease, bool)
	MarkSuccess(proxyAddress string) bool
	MarkCooldown(proxyAddress string, cooldownFor time.Duration)
}

type ExecutionOptions struct {
	Target          int
	Threads         int
	MaxRetries      int
	FailStop        bool
	RetryDelay      time.Duration
	CooldownOnError time.Duration
	LeaseManager    LeaseManager
	Now             func() time.Time
	ConfigureRun    func(ctx context.Context, jobIndex int, attempt int, cfg *RuntimeConfig) error
}

type SubmitFunc func(ctx context.Context, cfg *RuntimeConfig, handler EventHandler) (*RunResult, error)

func ClassifyRunError(err error) ErrorKind {
	if err == nil {
		return ""
	}
	switch {
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		return ErrorKindCanceled
	case errors.Is(err, ErrUnsupportedOperation):
		return ErrorKindUnsupported
	case errors.Is(err, ErrInvalidConfig), errors.Is(err, ErrPrepareConfigFailed):
		return ErrorKindConfig
	case errors.Is(err, ErrParseFailed):
		return ErrorKindParse
	}
	message := err.Error()
	switch {
	case strings.Contains(message, "解析"):
		return ErrorKindParse
	case strings.Contains(message, "配置") || strings.Contains(message, "答案"):
		return ErrorKindConfig
	default:
		return ErrorKindRun
	}
}
