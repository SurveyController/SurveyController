package surveycore

import (
	"context"
	"net/http"
	"strings"

	"surveycontroller/surveycore/credamo"
	"surveycontroller/surveycore/internal/httpjson"
	"surveycontroller/surveycore/internal/model"
)

type Client struct {
	httpClient HTTPClient
	aiAPIKey   string
	aiBaseURL  string
	aiModel    string
}

type Option func(*Client)

func New(opts ...Option) *Client {
	c := &Client{}
	for _, opt := range opts {
		if opt != nil {
			opt(c)
		}
	}
	return c
}

func WithHTTPClient(client *http.Client) Option {
	return func(c *Client) {
		c.httpClient = HTTPClient{Client: client}
	}
}

func WithAI(apiKey string, baseURL string, modelName string) Option {
	return func(c *Client) {
		c.aiAPIKey = strings.TrimSpace(apiKey)
		c.aiBaseURL = strings.TrimSpace(baseURL)
		c.aiModel = strings.TrimSpace(modelName)
	}
}

func Parse(ctx context.Context, surveyURL string) (*SurveyDefinition, error) {
	return New().Parse(ctx, surveyURL)
}

func DefaultConfig(ctx context.Context, surveyURL string) (*RuntimeConfig, error) {
	return New().DefaultConfig(ctx, surveyURL)
}

func Run(ctx context.Context, cfg *RuntimeConfig) (*RunResult, error) {
	return New().Run(ctx, cfg)
}

func (c *Client) parserFor(url string) (Parser, error) {
	if detectProvider(url) != model.ProviderCredamo {
		return nil, ErrUnsupportedOperation
	}
	return credamo.Parser{HTTP: httpClientOrDefault(c.httpClient)}, nil
}

func httpClientOrDefault(client HTTPClient) httpjson.Client {
	return httpjson.Client{Client: client.Client}
}

func detectProvider(rawURL string) string {
	lowered := strings.ToLower(strings.TrimSpace(rawURL))
	switch {
	case strings.Contains(lowered, "credamo.com") || strings.Contains(lowered, "credamo.cn"):
		return model.ProviderCredamo
	case strings.Contains(lowered, "127.0.0.1") || strings.Contains(lowered, "localhost"):
		if strings.Contains(lowered, "/s/") || strings.Contains(lowered, "#/s/") {
			return model.ProviderCredamo
		}
		return ""
	case strings.Contains(lowered, "wj.qq.com"):
		return model.ProviderQQ
	case strings.Contains(lowered, "wjx.cn") || strings.Contains(lowered, "wjx.com") || strings.Contains(lowered, "wjx.top"):
		return model.ProviderWJX
	default:
		return ""
	}
}
