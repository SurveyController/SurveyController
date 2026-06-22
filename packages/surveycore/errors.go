package surveycore

import "errors"

var (
	ErrInvalidConfig        = errors.New("invalid config")
	ErrParseFailed          = errors.New("parse survey failed")
	ErrPrepareConfigFailed  = errors.New("prepare execution config failed")
	ErrRunFailed            = errors.New("run failed")
	ErrUnsupportedOperation = errors.New("unsupported operation")
)
