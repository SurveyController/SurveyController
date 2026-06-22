package surveycore

import (
	"context"
	"fmt"
	"strings"
)

func (c *Client) Parse(ctx context.Context, surveyURL string) (*SurveyDefinition, error) {
	surveyURL = strings.TrimSpace(surveyURL)
	if surveyURL == "" {
		return nil, fmt.Errorf("%w: url 不能为空", ErrInvalidConfig)
	}
	parser, err := c.parserFor(surveyURL)
	if err != nil {
		return nil, fmt.Errorf("%w: %s", err, detectProvider(surveyURL))
	}
	definition, err := parser.Parse(ctx, surveyURL)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrParseFailed, err)
	}
	return &definition, nil
}
