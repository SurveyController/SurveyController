package surveycore

import (
	"context"

	"surveycontroller/surveycore/internal/model"
)

const (
	ProviderWJX     = model.ProviderWJX
	ProviderQQ      = model.ProviderQQ
	ProviderCredamo = model.ProviderCredamo

	LogicParseStatusNone    = model.LogicParseStatusNone
	LogicParseStatusUnknown = model.LogicParseStatusUnknown
)

type SurveyDefinition = model.SurveyDefinition
type QuestionMeta = model.QuestionMeta
type RuntimeConfig = model.RuntimeConfig
type QuestionEntry = model.QuestionEntry
type RunResult = model.RunResult
type ThreadProgress = model.ThreadProgress
type Event = model.Event

type Parser interface {
	Parse(ctx context.Context, surveyURL string) (SurveyDefinition, error)
}
