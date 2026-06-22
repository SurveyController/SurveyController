package credamo

import (
	"context"
	"time"

	"surveycontroller/surveycore/internal/httpjson"
	"surveycontroller/surveycore/internal/model"
)

type ParseError struct {
	Message string
}

func (e ParseError) Error() string {
	return e.Message
}

type Parser struct {
	HTTP interface {
		DoJSON(ctx context.Context, method string, url string, headers map[string]string, body any, out any) error
	}
	UserAgent string
}

type Event struct {
	Worker  string
	Message string
	Success bool
	Fail    bool
	Current int
	Total   int
	Time    time.Time
}

type EventHandler func(Event)

type Result struct {
	Success int
	Fail    int
	Target  int
	Status  string
}

type Runner struct {
	HTTP interface {
		DoJSON(ctx context.Context, method string, url string, headers map[string]string, body any, out any) error
	}
	UserAgent string
}

type runConfig interface {
	GetURL() string
}

type submitContext struct {
	Origin       string
	ShortURL     string
	Detail       map[string]any
	RawQuestions []map[string]any
	Config       *model.RuntimeConfig
}

type answerInit struct {
	AnswerToken string
	TimestampMS int64
	TimeCode    string
}

type apiEnvelope struct {
	Success *bool `json:"success"`
	Code    any   `json:"code"`
	Message any   `json:"message"`
	Msg     any   `json:"msg"`
	Data    any   `json:"data"`
}

func httpDoerOrDefault(client interface {
	DoJSON(ctx context.Context, method string, url string, headers map[string]string, body any, out any) error
}) interface {
	DoJSON(ctx context.Context, method string, url string, headers map[string]string, body any, out any) error
} {
	if client != nil {
		return client
	}
	return httpjson.Client{}
}
