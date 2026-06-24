package surveycore

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const (
	aiModeFree            = "free"
	aiModeProvider        = "provider"
	aiProviderCustom      = "custom"
	aiProtocolAuto        = "auto"
	aiProtocolChat        = "chat_completions"
	aiProtocolResponses   = "responses"
	chatCompletionsSuffix = "/chat/completions"
	responsesSuffix       = "/responses"
	legacyCompletions     = "/completions"
	defaultFreeAIURL      = "https://api-wjx.hungrym0.com/api/ai/free"
	defaultDeepSeekURL    = "https://api.deepseek.com/v1"
	defaultDeepSeekModel  = "deepseek-v4-flash"
	defaultAISystemPrompt = "你现在是一名普通问卷填写者。只输出答案本身，不要解释。回答尽量简短、自然。"
	optionFillAIToken     = "__AI_FILL__"
)

type AITextRequest struct {
	QuestionNum int
	Title       string
	Description string
	BlankCount  int
}

type AITextResolver interface {
	ResolveText(ctx context.Context, cfg RuntimeConfig, request AITextRequest) ([]string, error)
}

type AITextResolverFunc func(ctx context.Context, cfg RuntimeConfig, request AITextRequest) ([]string, error)

func (fn AITextResolverFunc) ResolveText(ctx context.Context, cfg RuntimeConfig, request AITextRequest) ([]string, error) {
	return fn(ctx, cfg, request)
}

type FreeAIIdentityProvider interface {
	FreeAIIdentity(ctx context.Context) (userID int, deviceID string, err error)
}

type FreeAIIdentityProviderFunc func(ctx context.Context) (userID int, deviceID string, err error)

func (fn FreeAIIdentityProviderFunc) FreeAIIdentity(ctx context.Context) (int, string, error) {
	return fn(ctx)
}

func (c *Client) resolveAIText(ctx context.Context, cfg RuntimeConfig, request AITextRequest) ([]string, error) {
	if c != nil && c.aiTextResolver != nil {
		return c.aiTextResolver.ResolveText(ctx, cfg, request)
	}
	return c.defaultAITextResolver(ctx, cfg, request)
}

func (c *Client) defaultAITextResolver(ctx context.Context, cfg RuntimeConfig, request AITextRequest) ([]string, error) {
	mode := strings.ToLower(strings.TrimSpace(cfg.AIMode))
	if mode == "" {
		mode = aiModeFree
	}
	if mode == aiModeFree {
		return c.callFreeAI(ctx, cfg, request)
	}
	return c.callProviderAI(ctx, cfg, request)
}

func (c *Client) callFreeAI(ctx context.Context, cfg RuntimeConfig, request AITextRequest) ([]string, error) {
	if c == nil || c.freeAIIdentityProvider == nil {
		return nil, fmt.Errorf("免费 AI 需要桌面端官方会话")
	}
	userID, deviceID, err := c.freeAIIdentityProvider.FreeAIIdentity(ctx)
	if err != nil {
		return nil, err
	}
	if userID <= 0 || strings.TrimSpace(deviceID) == "" {
		return nil, fmt.Errorf("免费 AI 身份无效")
	}
	endpoint := strings.TrimSpace(cfg.AIBaseURL)
	if endpoint == "" {
		endpoint = defaultFreeAIURL
	}
	payload := map[string]any{
		"user_id":          userID,
		"question_type":    aiQuestionType(request.BlankCount),
		"question_content": aiQuestionPrompt(cfg, request),
	}
	if request.BlankCount > 1 {
		payload["blank_count"] = request.BlankCount
	}
	if prompt := strings.TrimSpace(cfg.AISystemPrompt); prompt != "" {
		payload["system_prompt"] = prompt
	}
	var response struct {
		Answers []string `json:"answers"`
		Detail  any      `json:"detail"`
		Error   any      `json:"error"`
		Message any      `json:"message"`
	}
	headers := map[string]string{
		"Content-Type": "application/json",
		"Accept":       "application/json",
		"User-Agent":   "SurveyController/Go",
		"X-Device-ID":  strings.TrimSpace(deviceID),
	}
	if err := c.doAIJSON(ctx, http.MethodPost, endpoint, headers, payload, &response); err != nil {
		return nil, err
	}
	return normalizeAIAnswers(response.Answers, request.BlankCount)
}

func (c *Client) callProviderAI(ctx context.Context, cfg RuntimeConfig, request AITextRequest) ([]string, error) {
	apiKey := firstNonEmpty(cfg.AIAPIKey, c.aiAPIKey)
	if apiKey == "" {
		return nil, fmt.Errorf("AI 配置不完整：缺少 API Key")
	}
	provider := strings.ToLower(strings.TrimSpace(cfg.AIProvider))
	baseURL := firstNonEmpty(cfg.AIBaseURL, c.aiBaseURL)
	if baseURL == "" && provider == aiProviderCustom {
		return nil, fmt.Errorf("AI 配置不完整：缺少 Base URL")
	}
	if baseURL == "" {
		baseURL = defaultDeepSeekURL
	}
	model := firstNonEmpty(cfg.AIModel, c.aiModel)
	if model == "" && provider == aiProviderCustom {
		return nil, fmt.Errorf("AI 配置不完整：缺少模型 ID")
	}
	if model == "" {
		model = defaultDeepSeekModel
	}
	protocol, endpoint, explicit, err := resolveAIEndpoint(baseURL, cfg.AIAPIProtocol)
	if err != nil {
		return nil, err
	}
	if protocol == aiProtocolResponses {
		return c.callResponsesAI(ctx, cfg, request, endpoint, apiKey, model)
	}
	answers, err := c.callChatCompletionsAI(ctx, cfg, request, endpoint, apiKey, model)
	if err != nil && !explicit && normalizeAIAPIProtocol(cfg.AIAPIProtocol) == aiProtocolAuto && isEndpointMismatchError(err) {
		_, fallbackEndpoint, _, fallbackErr := resolveAIEndpoint(baseURL, aiProtocolResponses)
		if fallbackErr != nil {
			return nil, fallbackErr
		}
		return c.callResponsesAI(ctx, cfg, request, fallbackEndpoint, apiKey, model)
	}
	return answers, err
}

func (c *Client) callChatCompletionsAI(ctx context.Context, cfg RuntimeConfig, request AITextRequest, endpoint string, apiKey string, model string) ([]string, error) {
	payload := map[string]any{
		"model": model,
		"messages": []map[string]string{
			{"role": "system", "content": firstNonEmpty(cfg.AISystemPrompt, defaultAISystemPrompt)},
			{"role": "user", "content": aiQuestionPrompt(cfg, request)},
		},
		"max_tokens":  200,
		"temperature": 0.7,
	}
	var response struct {
		Choices []struct {
			Message struct {
				Content any `json:"content"`
			} `json:"message"`
		} `json:"choices"`
		Error any `json:"error"`
	}
	headers := map[string]string{
		"Content-Type":  "application/json",
		"Accept":        "application/json",
		"Authorization": "Bearer " + apiKey,
	}
	if err := c.doAIJSON(ctx, http.MethodPost, endpoint, headers, payload, &response); err != nil {
		return nil, err
	}
	if len(response.Choices) == 0 {
		return nil, fmt.Errorf("AI 未返回答案")
	}
	text := strings.Join(extractAITextParts(response.Choices[0].Message.Content), "\n")
	if strings.TrimSpace(text) == "" {
		return nil, fmt.Errorf("AI 未返回答案")
	}
	return normalizeProviderAnswer(text, request.BlankCount)
}

func (c *Client) callResponsesAI(ctx context.Context, cfg RuntimeConfig, request AITextRequest, endpoint string, apiKey string, model string) ([]string, error) {
	payload := map[string]any{
		"model":             model,
		"instructions":      firstNonEmpty(cfg.AISystemPrompt, defaultAISystemPrompt),
		"input":             aiQuestionPrompt(cfg, request),
		"max_output_tokens": 200,
		"temperature":       0.7,
	}
	var response struct {
		OutputText string `json:"output_text"`
		Output     []struct {
			Content any `json:"content"`
		} `json:"output"`
		Error any `json:"error"`
	}
	headers := map[string]string{
		"Content-Type":  "application/json",
		"Accept":        "application/json",
		"Authorization": "Bearer " + apiKey,
	}
	if err := c.doAIJSON(ctx, http.MethodPost, endpoint, headers, payload, &response); err != nil {
		return nil, err
	}
	if text := strings.TrimSpace(response.OutputText); text != "" {
		return normalizeProviderAnswer(text, request.BlankCount)
	}
	for _, item := range response.Output {
		if text := strings.Join(extractAITextParts(item.Content), "\n"); strings.TrimSpace(text) != "" {
			return normalizeProviderAnswer(text, request.BlankCount)
		}
	}
	return nil, fmt.Errorf("AI 未返回答案")
}

func (c *Client) doAIJSON(ctx context.Context, method string, endpoint string, headers map[string]string, body any, out any) error {
	client := http.DefaultClient
	if c != nil && c.httpClient.Client != nil {
		client = c.httpClient.Client
	}
	data, err := json.Marshal(body)
	if err != nil {
		return err
	}
	reqCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(reqCtx, method, endpoint, bytes.NewReader(data))
	if err != nil {
		return err
	}
	for key, value := range headers {
		request.Header.Set(key, value)
	}
	response, err := client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	responseBody, err := io.ReadAll(response.Body)
	if err != nil {
		return err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("AI 请求失败：http %d: %s", response.StatusCode, strings.TrimSpace(string(responseBody)))
	}
	if err := json.Unmarshal(responseBody, out); err != nil {
		return err
	}
	return nil
}

func aiQuestionPrompt(cfg RuntimeConfig, request AITextRequest) string {
	parts := make([]string, 0, 3)
	if cfg.Persona != nil {
		parts = append(parts, "你扮演的角色是："+cfg.Persona.Description()+"。")
	}
	title := strings.TrimSpace(request.Title)
	if title == "" && request.QuestionNum > 0 {
		title = fmt.Sprintf("第%d题", request.QuestionNum)
	}
	if desc := strings.TrimSpace(request.Description); desc != "" && !strings.Contains(title, desc) {
		title = strings.TrimSpace(title + "\n补充说明：" + desc)
	}
	parts = append(parts, title)
	if request.BlankCount > 1 {
		parts = append(parts, fmt.Sprintf("请按顺序给出 %d 个空位答案，用 || 分隔。", request.BlankCount))
		return strings.Join(parts, "\n")
	}
	parts = append(parts, "请只输出最终答案。")
	return strings.Join(parts, "\n")
}

func endpointWithSuffix(baseURL string, suffix string) string {
	base := strings.TrimRight(strings.TrimSpace(baseURL), "/")
	if strings.HasSuffix(strings.ToLower(base), suffix) {
		return base
	}
	return base + suffix
}

func resolveAIEndpoint(baseURL string, protocol string) (string, string, bool, error) {
	base := strings.TrimRight(strings.TrimSpace(baseURL), "/")
	if base == "" {
		return "", "", false, fmt.Errorf("AI 配置不完整：缺少 Base URL")
	}
	lower := strings.ToLower(base)
	if strings.HasSuffix(lower, chatCompletionsSuffix) {
		return aiProtocolChat, base, true, nil
	}
	if strings.HasSuffix(lower, responsesSuffix) {
		return aiProtocolResponses, base, true, nil
	}
	if strings.HasSuffix(lower, legacyCompletions) {
		return "", "", false, fmt.Errorf("暂不支持旧版 /completions 协议，请改用 /chat/completions 或 /responses")
	}
	if normalizeAIAPIProtocol(protocol) == aiProtocolResponses {
		return aiProtocolResponses, endpointWithSuffix(base, responsesSuffix), false, nil
	}
	return aiProtocolChat, endpointWithSuffix(base, chatCompletionsSuffix), false, nil
}

func normalizeAIAPIProtocol(protocol string) string {
	switch strings.ToLower(strings.TrimSpace(protocol)) {
	case aiProtocolChat:
		return aiProtocolChat
	case aiProtocolResponses:
		return aiProtocolResponses
	default:
		return aiProtocolAuto
	}
}

func isEndpointMismatchError(err error) bool {
	message := strings.ToLower(strings.TrimSpace(fmt.Sprint(err)))
	for _, marker := range []string{
		"404",
		"405",
		"410",
		"not found",
		"no route",
		"no handler",
		"unsupported path",
		"invalid url",
		"method not allowed",
	} {
		if strings.Contains(message, marker) {
			return true
		}
	}
	return false
}

func extractAITextParts(content any) []string {
	switch value := content.(type) {
	case nil:
		return nil
	case string:
		if text := strings.TrimSpace(value); text != "" {
			return []string{text}
		}
	case []any:
		parts := make([]string, 0, len(value))
		for _, item := range value {
			parts = append(parts, extractAITextParts(item)...)
		}
		return parts
	case map[string]any:
		itemType := strings.ToLower(strings.TrimSpace(aiStringValue(value["type"])))
		text := firstNonEmpty(aiStringValue(value["text"]), aiStringValue(value["content"]))
		if text == "" {
			return nil
		}
		if itemType == "" || itemType == "text" || itemType == "output_text" || itemType == "input_text" {
			return []string{text}
		}
	}
	return nil
}

func aiStringValue(value any) string {
	switch typed := value.(type) {
	case nil:
		return ""
	case string:
		return typed
	case fmt.Stringer:
		return typed.String()
	default:
		return fmt.Sprint(typed)
	}
}

func aiQuestionType(blankCount int) string {
	if blankCount > 1 {
		return "multi_fill_blank"
	}
	return "fill_blank"
}

func normalizeProviderAnswer(raw string, blankCount int) ([]string, error) {
	if blankCount <= 1 {
		text := strings.TrimSpace(raw)
		if text == "" {
			return nil, fmt.Errorf("AI 未返回答案")
		}
		return []string{text}, nil
	}
	parts := strings.Split(raw, "||")
	answers := make([]string, 0, len(parts))
	for _, part := range parts {
		if text := strings.TrimSpace(part); text != "" {
			answers = append(answers, text)
		}
	}
	return normalizeAIAnswers(answers, blankCount)
}

func normalizeAIAnswers(raw []string, blankCount int) ([]string, error) {
	if blankCount <= 0 {
		blankCount = 1
	}
	answers := make([]string, 0, len(raw))
	for _, item := range raw {
		if text := strings.TrimSpace(item); text != "" {
			answers = append(answers, text)
		}
	}
	if len(answers) == 0 {
		return nil, fmt.Errorf("AI 未返回答案")
	}
	if blankCount > 1 && len(answers) != blankCount {
		return nil, fmt.Errorf("AI 返回答案数量不匹配：期望 %d，实际 %d", blankCount, len(answers))
	}
	if blankCount == 1 && len(answers) > 1 {
		return answers[:1], nil
	}
	return answers, nil
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if text := strings.TrimSpace(value); text != "" {
			return text
		}
	}
	return ""
}
