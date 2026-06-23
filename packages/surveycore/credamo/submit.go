package credamo

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"time"

	"surveycontroller/surveycore/internal/httpjson"
	"surveycontroller/surveycore/internal/model"
	"surveycontroller/surveycore/internal/proxyhttp"
)

const resolution = "1920px*1080px"

func (r Runner) Run(ctx context.Context, cfg *model.RuntimeConfig, handler EventHandler) (Result, error) {
	target := cfg.Target
	if target <= 0 {
		target = 1
	}
	result := Result{Target: target, Status: "pending"}
	if cfg.URL == "" {
		return result, fmt.Errorf("配置为空")
	}

	parser := Parser{HTTP: r.HTTP, UserAgent: r.UserAgent}
	origin, shortURL, detail, err := parser.FetchDetailForRun(ctx, cfg.URL)
	if err != nil {
		return result, fmt.Errorf("解析问卷失败: %w", err)
	}
	rawQuestions := iterRawQuestions(detail)
	if len(rawQuestions) == 0 {
		return result, fmt.Errorf("解析问卷失败: 见数详情接口未返回可提交题目")
	}
	if cfg.SurveyProvider == "" {
		cfg.SurveyProvider = model.ProviderCredamo
	}
	if cfg.SurveyTitle == "" {
		cfg.SurveyTitle = surveyTitle(detail)
	}
	emit(handler, "解析成功", false, false, 0, target)

	for i := 0; i < target; i++ {
		if err := ctx.Err(); err != nil {
			result.Status = "stopped"
			return result, err
		}
		initData, err := r.initAnswer(ctx, origin, shortURL, cfg.ActiveProxyAddress)
		if err != nil {
			result.Fail++
			emit(handler, "初始化失败", false, true, result.Success+result.Fail, target)
			return result, fmt.Errorf("提交失败: %w", err)
		}
		answers, err := buildAnswerItems(rawQuestions, cfg)
		if err != nil {
			result.Fail++
			emit(handler, "生成答案失败", false, true, result.Success+result.Fail, target)
			return result, fmt.Errorf("生成答案失败: %w", err)
		}
		body := map[string]any{
			"answerStartTime": initData.TimestampMS,
			"answerEndTime":   initData.TimestampMS + int64(defaultDurationSeconds(cfg))*1000,
			"status":          1,
			"answerQstList":   answers,
			"shortUrl":        shortURL,
			"resolution":      resolution,
			"sourceDetail":    1,
		}
		if err := r.saveAnswers(ctx, origin, shortURL, initData, body, cfg.ActiveProxyAddress); err != nil {
			result.Fail++
			emit(handler, "提交失败", false, true, result.Success+result.Fail, target)
			return result, fmt.Errorf("提交失败: %w", err)
		}
		result.Success++
		emit(handler, "提交成功", true, false, result.Success+result.Fail, target)
	}
	result.Status = "success"
	return result, nil
}

func (r Runner) initAnswer(ctx context.Context, origin string, shortURL string, proxyAddress string) (answerInit, error) {
	timeCode := fmt.Sprintf("%d", time.Now().UnixNano())
	headers := requestHeaders(origin, shortURL, r.UserAgent, "")
	endpoint := fmt.Sprintf("%s/v1/survey/answer/noauth/init/%s?timeCode=%s&accountCode=CDM&resolution=%s", strings.TrimRight(origin, "/"), shortURL, timeCode, resolution)
	var payload apiEnvelope
	doer, err := r.httpDoer(proxyAddress)
	if err != nil {
		return answerInit{}, err
	}
	if err := doer.DoJSON(ctx, http.MethodGet, endpoint, headers, nil, &payload); err != nil {
		return answerInit{}, err
	}
	data, err := ensureAPIOK(payload, "初始化")
	if err != nil {
		return answerInit{}, err
	}
	token := strings.TrimSpace(stringValue(data["answerToken"]))
	if token == "" {
		return answerInit{}, fmt.Errorf("见数初始化接口未返回 answerToken")
	}
	timestamp := int64Value(data["timestamp"])
	if timestamp <= 0 {
		timestamp = time.Now().UnixMilli()
	}
	return answerInit{AnswerToken: token, TimestampMS: timestamp, TimeCode: timeCode}, nil
}

func (r Runner) saveAnswers(ctx context.Context, origin string, shortURL string, initData answerInit, body map[string]any, proxyAddress string) error {
	headers := requestHeaders(origin, shortURL, r.UserAgent, initData.AnswerToken)
	headers["Origin"] = strings.TrimRight(origin, "/")
	headers["Content-Type"] = "application/json"
	endpoint := fmt.Sprintf("%s/v1/survey/answer/noauth/save?timeCode=%s&answerToken=%s", strings.TrimRight(origin, "/"), initData.TimeCode, initData.AnswerToken)
	var payload apiEnvelope
	doer, err := r.httpDoer(proxyAddress)
	if err != nil {
		return err
	}
	if err := doer.DoJSON(ctx, http.MethodPost, endpoint, headers, body, &payload); err != nil {
		return err
	}
	_, err = ensureAPIOK(payload, "提交")
	return err
}

func (r Runner) httpDoer(proxyAddress string) (interface {
	DoJSON(ctx context.Context, method string, url string, headers map[string]string, body any, out any) error
}, error) {
	if strings.TrimSpace(proxyAddress) == "" {
		return httpDoerOrDefault(r.HTTP), nil
	}
	client, err := proxyhttp.Client(nil, proxyAddress)
	if err != nil {
		return nil, err
	}
	return httpjson.Client{Client: client}, nil
}

func defaultDurationSeconds(cfg *model.RuntimeConfig) int {
	if cfg.AnswerDuration[0] > 0 {
		return cfg.AnswerDuration[0]
	}
	return 60
}

func emit(handler EventHandler, message string, success bool, fail bool, current int, total int) {
	if handler == nil {
		return
	}
	handler(Event{
		Worker:  "Worker-1",
		Message: message,
		Success: success,
		Fail:    fail,
		Current: current,
		Total:   total,
		Time:    time.Now(),
	})
}
