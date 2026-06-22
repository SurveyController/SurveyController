package tencent

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"time"

	"surveycontroller/surveycore/internal/model"
)

var locales = []string{"zhs", "zht", "zh", "en"}

func (p Parser) Parse(ctx context.Context, surveyURL string) (model.SurveyDefinition, error) {
	if isLoginRequiredURL(surveyURL) {
		return model.SurveyDefinition{}, ParseError{Message: "作答该问卷需要登录，请自行在后台开放访问权限"}
	}
	surveyID, hashValue, err := extractIdentifiers(surveyURL)
	if err != nil {
		return model.SurveyDefinition{}, err
	}
	definition, err := p.fetchViaHTTP(ctx, surveyID, hashValue)
	if err != nil {
		return model.SurveyDefinition{}, err
	}
	if len(definition.Questions) == 0 {
		return model.SurveyDefinition{}, ParseError{Message: "腾讯问卷解析结果为空"}
	}
	return definition, nil
}

func (p Parser) fetchViaHTTP(ctx context.Context, surveyID string, hashValue string) (model.SurveyDefinition, error) {
	headers := apiHeaders(pageURL(surveyID, hashValue), p.UserAgent)
	if _, err := p.requestAPI(ctx, surveyID, "session", hashValue, headers, nil); err != nil {
		return model.SurveyDefinition{}, err
	}

	var lastErr error
	for _, locale := range locales {
		meta, err := p.requestAPI(ctx, surveyID, "meta", hashValue, headers, map[string]string{"locale": locale})
		if err != nil {
			lastErr = err
			continue
		}
		questionsData, err := p.requestAPI(ctx, surveyID, "questions", hashValue, headers, map[string]string{"locale": locale})
		if err != nil {
			lastErr = err
			continue
		}
		questions := asMapList(questionsData["questions"])
		if len(questions) == 0 {
			lastErr = fmt.Errorf("腾讯问卷题目接口未返回可解析题目（locale=%s）", locale)
			continue
		}
		definition, err := buildDefinition(questions, firstString(meta["title"]))
		if err != nil {
			return model.SurveyDefinition{}, err
		}
		return definition, nil
	}
	if lastErr != nil {
		return model.SurveyDefinition{}, fmt.Errorf("腾讯问卷 HTTP 解析失败：%w", lastErr)
	}
	return model.SurveyDefinition{}, ParseError{Message: "腾讯问卷 HTTP 解析失败：未获得可用 locale"}
}

func (p Parser) requestAPI(ctx context.Context, surveyID string, endpoint string, hashValue string, headers map[string]string, extraParams map[string]string) (map[string]any, error) {
	query := fmt.Sprintf("hash=%s&_=%d", hashValue, time.Now().UnixMilli())
	for key, value := range extraParams {
		query += "&" + key + "=" + value
	}
	url := apiEndpoint(surveyID, endpoint) + "?" + query
	var payload apiEnvelope
	if err := httpDoerOrDefault(p.HTTP).DoJSON(ctx, http.MethodGet, url, headers, nil, &payload); err != nil {
		return nil, err
	}
	return ensureAPIOK(payload, endpoint)
}

func ensureAPIOK(payload apiEnvelope, endpoint string) (map[string]any, error) {
	if isLoginRequiredError(payload) {
		return nil, ParseError{Message: "作答该问卷需要登录，请自行在后台开放访问权限"}
	}
	code := strings.ToUpper(strings.TrimSpace(stringValue(payload.Code)))
	if code != "OK" && code != "0" {
		return nil, fmt.Errorf("腾讯问卷接口返回异常（%s）：%s", endpoint, firstString(payload.Code, payload.Message, payload.Msg, "unknown"))
	}
	data, ok := payload.Data.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("腾讯问卷接口缺少 data 对象：%s", endpoint)
	}
	return data, nil
}

func apiHeaders(referer string, userAgent string) map[string]string {
	ua := strings.TrimSpace(userAgent)
	if ua == "" {
		ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
	}
	return map[string]string{
		"Accept":     "application/json, text/plain, */*",
		"Origin":     "https://wj.qq.com",
		"Referer":    referer,
		"User-Agent": ua,
	}
}

func isLoginRequiredError(value any) bool {
	if value == nil {
		return false
	}
	switch typed := value.(type) {
	case apiEnvelope:
		return isLoginRequiredError(typed.Code) || isLoginRequiredError(typed.Message) || isLoginRequiredError(typed.Msg) || isLoginRequiredError(typed.Data)
	case map[string]any:
		for key, item := range typed {
			if isLoginRequiredError(key) || isLoginRequiredError(item) {
				return true
			}
		}
	case []any:
		for _, item := range typed {
			if isLoginRequiredError(item) {
				return true
			}
		}
	default:
		text := strings.ToLower(strings.TrimSpace(stringValue(value)))
		for _, token := range []string{"open.weixin.qq.com/connect/confirm", "wj.qq.com/r/login.html", "/r/login.html", "need login", "login required", "require login", "未登录", "需登录", "需要登录"} {
			if strings.Contains(text, token) {
				return true
			}
		}
	}
	return false
}
