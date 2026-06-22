package credamo

import (
	"context"
	"fmt"
	"net/http"
	"strings"

	"surveycontroller/surveycore/internal/model"
)

func (p Parser) Parse(ctx context.Context, surveyURL string) (model.SurveyDefinition, error) {
	origin := originFromURL(surveyURL)
	short, err := shortURLFromURL(surveyURL)
	if err != nil {
		return model.SurveyDefinition{}, err
	}
	noAuthShort, err := noAuthShortURL(short)
	if err != nil {
		return model.SurveyDefinition{}, err
	}

	detail, err := p.fetchDetail(ctx, origin, noAuthShort)
	if err != nil {
		return model.SurveyDefinition{}, err
	}
	questions := make([]model.QuestionMeta, 0)
	for index, raw := range iterRawQuestions(detail) {
		normalized := normalizeQuestion(rawToNormalizedInput(raw, index+1), index+1)
		if isAnswerableQuestion(normalized) {
			questions = append(questions, normalized)
		}
	}
	if len(questions) == 0 {
		return model.SurveyDefinition{}, ParseError{Message: "见数详情接口未返回可解析题目，请确认链接为免登录问卷且已开放"}
	}
	return model.SurveyDefinition{
		Provider:  model.ProviderCredamo,
		Title:     surveyTitle(detail),
		Questions: questions,
	}, nil
}

func (p Parser) fetchDetail(ctx context.Context, origin string, shortURL string) (map[string]any, error) {
	headers := requestHeaders(origin, shortURL, p.UserAgent, "")
	endpoint := fmt.Sprintf("%s/v1/survey/noauth/detail/get/%s", strings.TrimRight(origin, "/"), shortURL)
	var payload apiEnvelope
	if err := httpDoerOrDefault(p.HTTP).DoJSON(ctx, http.MethodGet, endpoint, headers, nil, &payload); err != nil {
		return nil, err
	}
	return ensureAPIOK(payload, "详情")
}

func (p Parser) FetchDetailForRun(ctx context.Context, surveyURL string) (origin string, shortURL string, detail map[string]any, err error) {
	origin = originFromURL(surveyURL)
	short, err := shortURLFromURL(surveyURL)
	if err != nil {
		return "", "", nil, err
	}
	shortURL, err = noAuthShortURL(short)
	if err != nil {
		return "", "", nil, err
	}
	detail, err = p.fetchDetail(ctx, origin, shortURL)
	return origin, shortURL, detail, err
}

func ensureAPIOK(payload apiEnvelope, label string) (map[string]any, error) {
	if payload.Success != nil && !*payload.Success {
		return nil, fmt.Errorf("见数%s失败：%s", label, firstString(payload.Message, payload.Msg, payload.Code))
	}
	data, ok := payload.Data.(map[string]any)
	if ok {
		return data, nil
	}
	if raw := envelopeToMap(payload); len(raw) > 0 {
		return raw, nil
	}
	return nil, fmt.Errorf("见数%s接口返回了非 JSON 对象", label)
}

func envelopeToMap(payload apiEnvelope) map[string]any {
	result := map[string]any{}
	if payload.Success != nil {
		result["success"] = *payload.Success
	}
	if payload.Code != nil {
		result["code"] = payload.Code
	}
	if payload.Message != nil {
		result["message"] = payload.Message
	}
	if payload.Msg != nil {
		result["msg"] = payload.Msg
	}
	if payload.Data != nil {
		result["data"] = payload.Data
	}
	return result
}
