package tencent

import (
	"context"
	"time"

	"surveycontroller/surveycore/internal/httpjson"
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

type apiEnvelope struct {
	Code    any `json:"code"`
	Message any `json:"message"`
	Msg     any `json:"msg"`
	Data    any `json:"data"`
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

type Result struct {
	Success int
	Fail    int
	Target  int
	Status  string
}

type EventHandler func(Event)

type Runner struct{}

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
