package tencent

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"time"

	"surveycontroller/surveycore/internal/answerplan"
	"surveycontroller/surveycore/internal/httpjson"
	"surveycontroller/surveycore/internal/model"
	"surveycontroller/surveycore/internal/proxyhttp"
)

func (r Runner) Run(ctx context.Context, cfg *model.RuntimeConfig, handler EventHandler) (Result, error) {
	target := 1
	if cfg != nil && cfg.Target > 0 {
		target = cfg.Target
	}
	result := Result{Target: target, Status: "pending"}
	if cfg == nil || strings.TrimSpace(cfg.URL) == "" {
		return result, fmt.Errorf("配置为空")
	}
	surveyID, hashValue, err := extractIdentifiers(cfg.URL)
	if err != nil {
		return result, err
	}
	page := pageURL(surveyID, hashValue)
	headers := apiHeaders(page, r.UserAgent)

	for index := 0; index < target; index++ {
		if err := ctx.Err(); err != nil {
			result.Status = "stopped"
			return result, err
		}
		answerSessionID, sessionData, rawQuestions, err := r.fetchSubmitSource(ctx, surveyID, hashValue, headers)
		if err != nil {
			result.Fail++
			emit(handler, "解析问卷失败", false, true, result.Success+result.Fail, target)
			return result, fmt.Errorf("解析问卷失败: %w", err)
		}
		body, err := buildSubmitBody(cfg, surveyID, hashValue, rawQuestions, r.UserAgent)
		if err != nil {
			result.Fail++
			emit(handler, "生成答案失败", false, true, result.Success+result.Fail, target)
			return result, fmt.Errorf("生成答案失败: %w", err)
		}
		if err := r.submitAnswers(ctx, cfg, surveyID, hashValue, page, answerSessionID, body); err != nil {
			result.Fail++
			emit(handler, "提交失败", false, true, result.Success+result.Fail, target)
			return result, fmt.Errorf("提交失败: %w", err)
		}
		if err := r.confirmSubmit(ctx, surveyID, hashValue, headers, answerSessionID, sessionData); err != nil {
			result.Fail++
			emit(handler, "校验失败", false, true, result.Success+result.Fail, target)
			return result, fmt.Errorf("提交失败: %w", err)
		}
		result.Success++
		emit(handler, "提交成功", true, false, result.Success+result.Fail, target)
	}
	result.Status = "success"
	return result, nil
}

func (r Runner) fetchSubmitSource(ctx context.Context, surveyID string, hashValue string, headers map[string]string) (string, map[string]any, []map[string]any, error) {
	sessionData, err := r.requestAPI(ctx, surveyID, "session", hashValue, headers, nil, "")
	if err != nil {
		return "", nil, nil, err
	}
	answerSessionID := strings.TrimSpace(stringValue(sessionData["answer_session_id"]))
	nextHeaders := cloneStringMap(headers)
	if answerSessionID != "" {
		nextHeaders["X-Answer-Session"] = answerSessionID
	}
	questionData, err := r.requestAPI(ctx, surveyID, "questions", hashValue, nextHeaders, map[string]string{"locale": "zhs"}, "")
	if err != nil {
		return "", nil, nil, err
	}
	rawQuestions := asMapList(questionData["questions"])
	if len(rawQuestions) == 0 {
		return "", nil, nil, fmt.Errorf("腾讯问卷题目接口未返回可提交题目")
	}
	return answerSessionID, sessionData, rawQuestions, nil
}

func buildSubmitBody(cfg *model.RuntimeConfig, surveyID string, hashValue string, rawQuestions []map[string]any, userAgent string) (map[string]any, error) {
	questions := submitQuestions(rawQuestions)
	index := answerplan.NewEntryIndex(cfg.QuestionEntries)
	actionByID := map[string]answerplan.Action{}
	for _, question := range questions {
		if question.IsDescription {
			continue
		}
		if label := blockedRuntimeProviderTypes[question.ProviderType]; label != "" {
			return nil, fmt.Errorf("腾讯问卷第%d题暂不支持：%s", question.Num, label)
		}
		if !supportedProviderTypes[question.ProviderType] {
			return nil, fmt.Errorf("腾讯问卷第%d题暂不支持：%s", question.Num, firstString(question.ProviderType, question.TypeCode, "unknown"))
		}
		entry, ok := index.Find(question)
		if !ok {
			entry = defaultEntry(question)
		}
		action, err := answerplan.BuildAction(question, entry)
		if err != nil {
			return nil, err
		}
		actionByID[question.ProviderID] = action
	}

	pages := make([]map[string]any, 0)
	pageIndex := map[string]int{}
	for _, raw := range rawQuestions {
		questionID := strings.TrimSpace(stringValue(raw["id"]))
		action, ok := actionByID[questionID]
		if !ok {
			continue
		}
		pageID := strings.TrimSpace(stringValue(raw["page_id"]))
		if pageID == "" {
			return nil, fmt.Errorf("腾讯问卷第%d题缺少 page_id", action.QuestionNum)
		}
		answer, err := questionAnswer(raw, action)
		if err != nil {
			return nil, err
		}
		idx, ok := pageIndex[pageID]
		if !ok {
			pageIndex[pageID] = len(pages)
			pages = append(pages, map[string]any{"id": pageID, "questions": []map[string]any{}})
			idx = len(pages) - 1
		}
		items := pages[idx]["questions"].([]map[string]any)
		if list, ok := answer.([]map[string]any); ok {
			items = append(items, list...)
		} else {
			items = append(items, answer.(map[string]any))
		}
		pages[idx]["questions"] = items
	}
	if len(pages) == 0 {
		return nil, fmt.Errorf("腾讯问卷没有生成可提交答案")
	}
	ua := strings.TrimSpace(userAgent)
	if ua == "" {
		ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
	}
	return map[string]any{
		"survey_id": intValue(surveyID),
		"hash":      hashValue,
		"answer_survey": map[string]any{
			"duration":  defaultDurationSeconds(cfg),
			"ua":        ua,
			"referrer":  "",
			"uid":       fmt.Sprintf("%d", time.Now().UnixNano()),
			"sid":       fmt.Sprintf("%d", time.Now().UnixNano()+1),
			"openid":    "",
			"latitude":  nil,
			"longitude": nil,
			"is_update": false,
			"locale":    "zhs",
			"pages":     pages,
		},
	}, nil
}

func submitQuestions(rawQuestions []map[string]any) []model.QuestionMeta {
	normalized := standardizeQuestions(rawQuestions)
	result := make([]model.QuestionMeta, 0, len(normalized))
	for _, question := range normalized {
		if !question.IsDescription {
			result = append(result, question)
		}
	}
	return result
}

func questionAnswer(raw map[string]any, action answerplan.Action) (any, error) {
	providerType := strings.TrimSpace(stringValue(raw["type"]))
	switch providerType {
	case "text", "textarea":
		return map[string]any{
			"id":   strings.TrimSpace(stringValue(raw["id"])),
			"type": providerType,
			"text": strings.Join(action.TextValues, "\n"),
		}, nil
	case "matrix_radio":
		return matrixAnswer(raw, action)
	default:
		return choiceAnswer(raw, action)
	}
}

func choiceAnswer(raw map[string]any, action answerplan.Action) (map[string]any, error) {
	options := asMapList(raw["options"])
	if len(options) == 0 {
		return nil, fmt.Errorf("腾讯问卷第%d题缺少选项", action.QuestionNum)
	}
	selected := map[int]bool{}
	for _, index := range action.SelectedIndices {
		selected[index] = true
	}
	answers := make([]map[string]any, 0, len(options))
	blanks := make([]map[string]any, 0)
	for index, option := range options {
		answers = append(answers, map[string]any{
			"id":      strings.TrimSpace(stringValue(option["id"])),
			"text":    strings.TrimSpace(stringValue(option["text"])),
			"checked": checkedInt(selected[index]),
		})
		if selected[index] {
			if fill := strings.TrimSpace(action.OptionFillTexts[index]); fill != "" {
				blanks = append(blanks, map[string]any{"id": optionBlankID(option), "text": fill})
			}
		}
	}
	return map[string]any{
		"id":      strings.TrimSpace(stringValue(raw["id"])),
		"type":    strings.TrimSpace(stringValue(raw["type"])),
		"blanks":  blanks,
		"options": answers,
	}, nil
}

func matrixAnswer(raw map[string]any, action answerplan.Action) ([]map[string]any, error) {
	rows := asMapList(raw["sub_titles"])
	options := asMapList(raw["options"])
	if len(rows) == 0 || len(options) == 0 {
		return nil, fmt.Errorf("腾讯问卷第%d题缺少矩阵行列", action.QuestionNum)
	}
	questionID := strings.TrimSpace(stringValue(raw["id"]))
	result := make([]map[string]any, 0, len(rows))
	for rowIndex, row := range rows {
		optionIndex := 0
		if rowIndex < len(action.MatrixIndices) {
			optionIndex = action.MatrixIndices[rowIndex]
		}
		if optionIndex < 0 || optionIndex >= len(options) {
			return nil, fmt.Errorf("腾讯问卷第%d题第%d行没有生成矩阵答案", action.QuestionNum, rowIndex+1)
		}
		rowID := strings.TrimSpace(stringValue(row["id"]))
		optionID := strings.TrimSpace(stringValue(options[optionIndex]["id"]))
		if optionID == "" {
			return nil, fmt.Errorf("腾讯问卷第%d题第%d行缺少矩阵列 id", action.QuestionNum, rowIndex+1)
		}
		id := questionID + "_" + optionID
		if rowID != "" {
			id = questionID + "_" + rowID + "_" + optionID
		}
		result = append(result, map[string]any{"id": id, "type": "matrix_radio", "answer": "on"})
	}
	return result, nil
}

func (r Runner) submitAnswers(ctx context.Context, cfg *model.RuntimeConfig, surveyID string, hashValue string, pageURL string, answerSessionID string, body map[string]any) error {
	headers := apiHeaders(pageURL, r.UserAgent)
	headers["Accept"] = "application/json, text/plain, */*"
	headers["Content-Type"] = "application/json;charset=UTF-8"
	if answerSessionID != "" {
		headers["X-Answer-Session"] = answerSessionID
	}
	endpoint := apiEndpoint(surveyID, "answers") + fmt.Sprintf("?pv_uid=%d&hash=%s&_=%d", time.Now().UnixNano(), hashValue, time.Now().UnixMilli())
	var payload apiEnvelope
	doer, err := r.httpDoer(cfg.ActiveProxyAddress)
	if err != nil {
		return err
	}
	if err := doer.DoJSON(ctx, http.MethodPost, endpoint, headers, body, &payload); err != nil {
		return err
	}
	code := strings.ToUpper(strings.TrimSpace(stringValue(payload.Code)))
	if code != "OK" && code != "0" {
		return fmt.Errorf("腾讯问卷提交失败：%s", firstString(payload.Message, payload.Msg, payload.Code, "unknown"))
	}
	return nil
}

func (r Runner) confirmSubmit(ctx context.Context, surveyID string, hashValue string, headers map[string]string, answerSessionID string, initial map[string]any) error {
	data := initial["answer_session"]
	initialSubmittedAt := 0
	if mapped, ok := data.(map[string]any); ok {
		initialSubmittedAt = intValue(mapped["last_submitted_at"])
	}
	if answerSessionID == "" {
		return nil
	}
	verifyHeaders := cloneStringMap(headers)
	verifyHeaders["X-Answer-Session"] = answerSessionID
	for attempt := 0; attempt < 3; attempt++ {
		sessionData, err := r.requestAPI(ctx, surveyID, "session", hashValue, verifyHeaders, nil, "")
		if err != nil {
			return err
		}
		if mapped, ok := sessionData["answer_session"].(map[string]any); ok {
			if intValue(mapped["last_submitted_at"]) > initialSubmittedAt || intValue(mapped["last_answer_id"]) > 0 {
				return nil
			}
		}
		if attempt < 2 {
			time.Sleep(200 * time.Millisecond)
		}
	}
	return fmt.Errorf("腾讯问卷提交后未确认到服务端已记录答案")
}

func (r Runner) requestAPI(ctx context.Context, surveyID string, endpoint string, hashValue string, headers map[string]string, extraParams map[string]string, proxyAddress string) (map[string]any, error) {
	query := fmt.Sprintf("hash=%s&_=%d", hashValue, time.Now().UnixMilli())
	for key, value := range extraParams {
		query += "&" + key + "=" + value
	}
	url := apiEndpoint(surveyID, endpoint) + "?" + query
	var payload apiEnvelope
	doer, err := r.httpDoer(proxyAddress)
	if err != nil {
		return nil, err
	}
	if err := doer.DoJSON(ctx, http.MethodGet, url, headers, nil, &payload); err != nil {
		return nil, err
	}
	return ensureAPIOK(payload, endpoint)
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

func defaultEntry(question model.QuestionMeta) model.QuestionEntry {
	num := question.Num
	providerID := question.ProviderID
	return model.QuestionEntry{
		QuestionType:       questionTypeName(question),
		Probabilities:      defaultProbabilities(question),
		Rows:               question.Rows,
		OptionCount:        maxInt(1, question.Options),
		QuestionNum:        &num,
		ProviderQuestionID: &providerID,
		SurveyProvider:     model.ProviderQQ,
	}
}

func questionTypeName(question model.QuestionMeta) string {
	switch question.ProviderType {
	case "radio":
		return "single"
	case "checkbox":
		return "multiple"
	case "select":
		return "dropdown"
	case "matrix_radio":
		return "matrix"
	case "text", "textarea":
		return "text"
	default:
		return "text"
	}
}

func defaultProbabilities(question model.QuestionMeta) []float64 {
	count := maxInt(1, question.Options)
	values := make([]float64, count)
	for i := range values {
		values[i] = 1
	}
	return values
}

func defaultDurationSeconds(cfg *model.RuntimeConfig) int {
	if cfg != nil && len(cfg.AnswerDuration) > 0 && cfg.AnswerDuration[0] > 0 {
		return cfg.AnswerDuration[0]
	}
	return 60
}

func optionBlankID(option map[string]any) string {
	for key, value := range option {
		if strings.Contains(strings.ToLower(key), "fillblank") {
			if text := strings.TrimSpace(stringValue(value)); text != "" {
				return text
			}
			return strings.TrimSpace(key)
		}
		if text := stringValue(value); fillBlankTokenRE.MatchString(text) {
			match := fillBlankTokenRE.FindStringSubmatch(text)
			if len(match) > 1 {
				return match[1]
			}
		}
	}
	return strings.TrimSpace(stringValue(option["id"]))
}

func checkedInt(value bool) int {
	if value {
		return 1
	}
	return 0
}

func cloneStringMap(src map[string]string) map[string]string {
	dst := make(map[string]string, len(src))
	for key, value := range src {
		dst[key] = value
	}
	return dst
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
