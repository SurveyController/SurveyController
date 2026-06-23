package surveycore

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestParseAndDefaultConfig(t *testing.T) {
	server := newCredamoTestServer(t, true)
	client := New()

	definition, err := client.Parse(context.Background(), server.URL+"/s/demo_")
	if err != nil {
		t.Fatal(err)
	}
	if definition.Provider != ProviderCredamo || len(definition.Questions) != 7 {
		t.Fatalf("definition = %#v", definition)
	}

	cfg, err := client.DefaultConfig(context.Background(), server.URL+"/s/demo_")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.SurveyProvider != ProviderCredamo || cfg.SurveyTitle != "Credamo 标题" {
		t.Fatalf("cfg = %#v", cfg)
	}
	if len(cfg.QuestionEntries) != 7 {
		t.Fatalf("entry count = %d", len(cfg.QuestionEntries))
	}
}

func TestParseAndDefaultConfigTencent(t *testing.T) {
	server := newTencentCoreTestServer(t)
	client := New(WithHTTPClient(rewriteTencentHTTPClient(server.URL)))

	definition, err := client.Parse(context.Background(), "https://wj.qq.com/s2/123/hashvalue/")
	if err != nil {
		t.Fatal(err)
	}
	if definition.Provider != ProviderQQ || len(definition.Questions) != 2 {
		t.Fatalf("definition = %#v", definition)
	}

	cfg, err := client.DefaultConfig(context.Background(), "https://wj.qq.com/s2/123/hashvalue/")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.SurveyProvider != ProviderQQ || cfg.SurveyTitle != "腾讯测试" {
		t.Fatalf("cfg = %#v", cfg)
	}
	if len(cfg.QuestionEntries) != 2 {
		t.Fatalf("entry count = %d", len(cfg.QuestionEntries))
	}
}

func TestParseDefaultConfigAndRunWJX(t *testing.T) {
	server := newWJXCoreTestServer(t, true)
	defer server.Close()
	client := New(WithHTTPClient(rewriteWJXHTTPClient(server.URL)))

	definition, err := client.Parse(context.Background(), "https://www.wjx.cn/vm/demo.aspx")
	if err != nil {
		t.Fatal(err)
	}
	if definition.Provider != ProviderWJX || len(definition.Questions) != 1 {
		t.Fatalf("definition = %#v", definition)
	}

	cfg, err := client.DefaultConfig(context.Background(), "https://www.wjx.cn/vm/demo.aspx")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.SurveyProvider != ProviderWJX || cfg.SurveyTitle != "WJX 测试" || len(cfg.QuestionEntries) != 1 {
		t.Fatalf("cfg = %#v", cfg)
	}
	cfg.Target = 1
	result, err := client.Run(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	if result.Success != 1 || result.Fail != 0 {
		t.Fatalf("result = %#v", result)
	}
}

func TestRunTencentSubmitsWithEvents(t *testing.T) {
	server := newTencentCoreTestServer(t)
	var events []Event
	result, err := New(WithHTTPClient(rewriteTencentHTTPClient(server.URL))).RunWithEvents(context.Background(), &RuntimeConfig{
		URL:            "https://wj.qq.com/s2/123/hashvalue/",
		SurveyProvider: ProviderQQ,
		Target:         1,
	}, func(event Event) {
		events = append(events, event)
	})
	if err != nil {
		t.Fatalf("err = %v", err)
	}
	if result == nil || result.Success != 1 || result.Fail != 0 {
		t.Fatalf("result = %#v", result)
	}
	if len(events) == 0 || !events[len(events)-1].Success {
		t.Fatalf("events = %#v", events)
	}
}

func TestRunWithEventsSubmitsCredamo(t *testing.T) {
	server := newCredamoTestServer(t, true)
	cfg, err := New().DefaultConfig(context.Background(), server.URL+"/s/demo_")
	if err != nil {
		t.Fatal(err)
	}
	cfg.Target = 1

	var events []Event
	result, err := New().RunWithEvents(context.Background(), cfg, func(event Event) {
		events = append(events, event)
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Success != 1 || result.Fail != 0 {
		t.Fatalf("result = %#v", result)
	}
	if len(events) == 0 {
		t.Fatal("expected events")
	}
}

func newTencentCoreTestServer(t *testing.T) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/v2/respondent/surveys/123/session":
			writeTestJSON(t, w, map[string]any{"code": "OK", "data": map[string]any{}})
		case "/api/v2/respondent/surveys/123/meta":
			writeTestJSON(t, w, map[string]any{"code": "OK", "data": map[string]any{"title": "腾讯测试 - 腾讯问卷"}})
		case "/api/v2/respondent/surveys/123/questions":
			writeTestJSON(t, w, map[string]any{
				"code": "OK",
				"data": map[string]any{
					"questions": []map[string]any{
						{"id": "q1", "type": "radio", "title": "单选", "page_id": "p1", "page": 1, "options": []map[string]any{{"id": "a", "text": "A"}, {"id": "b", "text": "B"}}},
						{"id": "q2", "type": "textarea", "title": "文本", "page_id": "p1", "page": 1},
					},
				},
			})
		case "/api/v2/respondent/surveys/123/answers":
			if r.Method != http.MethodPost {
				t.Fatalf("method = %s", r.Method)
			}
			var body map[string]any
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Fatalf("decode tencent submit body: %v", err)
			}
			answerSurvey, ok := body["answer_survey"].(map[string]any)
			if !ok {
				t.Fatalf("answer_survey = %#v", body["answer_survey"])
			}
			pages, ok := answerSurvey["pages"].([]any)
			if !ok || len(pages) != 1 {
				t.Fatalf("pages = %#v", answerSurvey["pages"])
			}
			writeTestJSON(t, w, map[string]any{"code": "OK", "data": map[string]any{"ok": true}})
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
}

func newWJXCoreTestServer(t *testing.T, submitOK bool) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/vm/demo.aspx":
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			_, _ = w.Write([]byte(`
<html><head><title>WJX 测试 - 问卷星</title></head><body>
<div id="divQuestion"><fieldset>
<div topic="1" id="div1" type="3"><div class="topichtml">1. 单选</div><div class="ui-controlgroup"><div><span class="label">A</span></div><div><span class="label">B</span></div></div></div>
</fieldset></div>
</body></html>`))
		case "/joinnew/processjq.ashx":
			if err := r.ParseForm(); err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(r.Form.Get("submitdata"), "1$") {
				t.Fatalf("submitdata = %q", r.Form.Get("submitdata"))
			}
			if submitOK {
				_, _ = w.Write([]byte("10"))
			} else {
				_, _ = w.Write([]byte("1〒1〒失败"))
			}
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
}

func rewriteTencentHTTPClient(baseURL string) *http.Client {
	return &http.Client{
		Transport: rewriteTencentTransport{
			baseURL: baseURL,
			next:    http.DefaultTransport,
		},
	}
}

type rewriteTencentTransport struct {
	baseURL string
	next    http.RoundTripper
}

func rewriteWJXHTTPClient(baseURL string) *http.Client {
	return &http.Client{
		Transport: rewriteWJXTransport{
			baseURL: baseURL,
			next:    http.DefaultTransport,
		},
	}
}

type rewriteWJXTransport struct {
	baseURL string
	next    http.RoundTripper
}

func (t rewriteWJXTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	if strings.Contains(req.URL.Host, "wjx.cn") || strings.Contains(req.URL.Host, "wjx.com") {
		rewritten, err := http.NewRequestWithContext(req.Context(), req.Method, strings.Replace(req.URL.String(), req.URL.Scheme+"://"+req.URL.Host, t.baseURL, 1), req.Body)
		if err != nil {
			return nil, err
		}
		rewritten.Header = req.Header.Clone()
		req = rewritten
	}
	return t.next.RoundTrip(req)
}

func (t rewriteTencentTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	if req.URL.Host == "wj.qq.com" {
		rewritten, err := http.NewRequestWithContext(req.Context(), req.Method, strings.Replace(req.URL.String(), "https://wj.qq.com", t.baseURL, 1), req.Body)
		if err != nil {
			return nil, err
		}
		rewritten.Header = req.Header.Clone()
		req = rewritten
	}
	return t.next.RoundTrip(req)
}

func TestRunErrors(t *testing.T) {
	_, err := Run(context.Background(), nil)
	if !errors.Is(err, ErrInvalidConfig) {
		t.Fatalf("nil config error = %v", err)
	}

	_, err = Run(context.Background(), &RuntimeConfig{URL: "https://example.com/s/1", SurveyProvider: "unknown"})
	if !errors.Is(err, ErrUnsupportedOperation) {
		t.Fatalf("unsupported error = %v", err)
	}

	server := newCredamoTestServer(t, false)
	cfg := &RuntimeConfig{URL: server.URL + "/s/demo_", SurveyProvider: ProviderCredamo, Target: 1}
	_, err = Run(context.Background(), cfg)
	if !errors.Is(err, ErrRunFailed) {
		t.Fatalf("run error = %v", err)
	}
}

func newCredamoTestServer(t *testing.T, submitOK bool) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/survey/noauth/detail/get/demoano":
			writeTestJSON(t, w, map[string]any{
				"success": true,
				"data": map[string]any{
					"surveyTitle": "Credamo 标题",
					"questions": []map[string]any{
						{"qstNo": "Q1", "qstTitle": "单选题", "questionType": 2, "selector": 1, "qstId": 101, "choices": []map[string]any{{"choiceId": 1, "display": "A"}, {"choiceId": 2, "display": "B"}}},
						{"qstNo": "Q2", "qstTitle": "多选题", "questionType": 2, "selector": 2, "qstId": 102, "choices": []map[string]any{{"choiceId": 3, "display": "A"}, {"choiceId": 4, "display": "B"}}},
						{"qstNo": "Q3", "qstTitle": "下拉题", "questionType": 2, "selector": 3, "qstId": 103, "choices": []map[string]any{{"choiceId": 5, "display": "A"}, {"choiceId": 6, "display": "B"}}},
						{"qstNo": "Q4", "qstTitle": "量表题", "questionType": 11, "qstId": 104, "choices": []map[string]any{{"choiceId": 7, "display": "1"}, {"choiceId": 8, "display": "2"}}},
						{"qstNo": "Q5", "qstTitle": "排序题", "questionType": 6, "qstId": 105, "choices": []map[string]any{{"choiceId": 9, "display": "A"}, {"choiceId": 10, "display": "B"}}},
						{"qstNo": "Q6", "qstTitle": "矩阵题", "questionType": 4, "qstId": 106, "choices": []map[string]any{{"choiceId": 11, "display": "行1"}, {"choiceId": 12, "display": "行2"}}, "answers": []map[string]any{{"answerId": 13, "display": "满意"}, {"answerId": 14, "display": "不满意"}}},
						{"qstNo": "Q7", "qstTitle": "文本题", "questionType": 1, "qstId": 107},
					},
				},
			})
		case "/v1/survey/answer/noauth/init/demoano":
			writeTestJSON(t, w, map[string]any{
				"success": true,
				"data": map[string]any{
					"answerToken": "token-1",
					"timestamp":   1700000000000,
				},
			})
		case "/v1/survey/answer/noauth/save":
			var body map[string]any
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Fatalf("decode submit body: %v", err)
			}
			items, ok := body["answerQstList"].([]any)
			if !ok || len(items) != 7 {
				t.Fatalf("answerQstList = %#v", body["answerQstList"])
			}
			writeTestJSON(t, w, map[string]any{"success": submitOK, "data": map[string]any{"ok": submitOK}})
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
}

func writeTestJSON(t *testing.T, w http.ResponseWriter, value any) {
	t.Helper()
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(value); err != nil {
		t.Fatal(err)
	}
}
