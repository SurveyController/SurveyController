package tencent

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"surveycontroller/surveycore/internal/model"
)

func TestParserParsesTencentQuestions(t *testing.T) {
	server := newTencentTestServer(t, false)
	parser := Parser{HTTP: rewriteClient(server.URL)}

	definition, err := parser.Parse(context.Background(), "https://wj.qq.com/s2/123/hashvalue/")
	if err != nil {
		t.Fatal(err)
	}
	if definition.Provider != model.ProviderQQ || definition.Title != "消费问卷" {
		t.Fatalf("definition = %#v", definition)
	}
	if len(definition.Questions) != 4 {
		t.Fatalf("question count = %d", len(definition.Questions))
	}
	first := definition.Questions[0]
	if first.ProviderType != "radio" || first.TypeCode != "3" || first.Options != 2 {
		t.Fatalf("first = %#v", first)
	}
	second := definition.Questions[1]
	if second.ProviderType != "checkbox" || second.TypeCode != "4" || len(second.FillableOptions) != 1 {
		t.Fatalf("second = %#v", second)
	}
	if second.MultiMinLimit == nil || *second.MultiMinLimit != 1 || second.MultiMaxLimit == nil || *second.MultiMaxLimit != 2 {
		t.Fatalf("multiple limits = %#v %#v", second.MultiMinLimit, second.MultiMaxLimit)
	}
	if len(second.QuestionMedia) == 0 {
		t.Fatalf("media = %#v", second.QuestionMedia)
	}
	matrix := definition.Questions[3]
	if matrix.Title != "说明文字 请评分" || matrix.Description != "请认真阅读" {
		t.Fatalf("merged matrix = %#v", matrix)
	}
	if matrix.ProviderType != "matrix_radio" || matrix.Rows != 2 || matrix.Options != 2 {
		t.Fatalf("matrix = %#v", matrix)
	}
}

func TestTencentAttachLogicMetadata(t *testing.T) {
	raw := []map[string]any{
		{"id": "q-1", "type": "radio", "title": "单选", "page_id": "p-1", "page": 1, "options": []any{map[string]any{"id": "o-1", "text": "A", "display": "q-2"}}},
		{"id": "q-2", "type": "text", "title": "文本", "page_id": "p-2", "page": 2, "hidden": true},
		{"id": "q-3", "type": "radio", "title": "跳转", "page_id": "p-2", "page": 2, "goto": map[string]any{"target": "q-2"}, "options": []any{map[string]any{"id": "o-2", "text": "B"}}},
	}
	questions := standardizeQuestions(raw)
	if len(questions) != 3 {
		t.Fatalf("questions = %#v", questions)
	}
	if !questions[1].HasDisplayCondition || questions[1].LogicStatus != model.LogicParseStatusComplete {
		t.Fatalf("display logic = %#v", questions[1])
	}
	if !questions[2].HasJump || len(questions[2].JumpRules) == 0 {
		t.Fatalf("jump logic = %#v", questions[2])
	}
}

func TestParserRejectsBlockedTencentRating(t *testing.T) {
	server := newTencentTestServer(t, true)
	parser := Parser{HTTP: rewriteClient(server.URL)}

	_, err := parser.Parse(context.Background(), "https://wj.qq.com/s2/123/hashvalue/")
	if err == nil || !strings.Contains(err.Error(), "请改用 v3.2.2 旧版本") {
		t.Fatalf("error = %v", err)
	}
}

func TestTencentHelpers(t *testing.T) {
	surveyID, hashValue, err := extractIdentifiers("https://wj.qq.com/s2/123/abc_hash/")
	if err != nil {
		t.Fatal(err)
	}
	if surveyID != "123" || hashValue != "abc_hash" {
		t.Fatalf("ids = %s %s", surveyID, hashValue)
	}
	if !isLoginRequiredURL("https://wj.qq.com/r/login.html") {
		t.Fatal("expected login url")
	}
	if cleanOptionText("其他 _{fillblank-1}") != "其他" {
		t.Fatalf("clean option failed")
	}
	if match := fillBlankTokenRE.FindStringSubmatch("{fillblank-1}"); len(match) < 2 || match[1] != "fillblank-1" {
		t.Fatalf("fillblank match = %#v", match)
	}
}

type rewriteClient string

func (c rewriteClient) DoJSON(ctx context.Context, method string, rawURL string, headers map[string]string, body any, out any) error {
	rewritten := strings.Replace(rawURL, "https://wj.qq.com", string(c), 1)
	var reader io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(data)
	}
	req, err := http.NewRequestWithContext(ctx, method, rewritten, reader)
	if err != nil {
		return err
	}
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("http %d", resp.StatusCode)
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func newTencentTestServer(t *testing.T, blocked bool) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/v2/respondent/surveys/123/session":
			writeTencentJSON(t, w, map[string]any{"code": "OK", "data": map[string]any{}})
		case "/api/v2/respondent/surveys/123/meta":
			writeTencentJSON(t, w, map[string]any{"code": "OK", "data": map[string]any{"title": "消费问卷 - 腾讯问卷"}})
		case "/api/v2/respondent/surveys/123/questions":
			questions := loadTencentQuestionsFixture(t)
			if blocked {
				questions = append(questions, map[string]any{"id": "q6", "type": "star", "title": "评分", "star_begin_num": 1, "star_num": 5, "page_id": "p3", "page": 3})
			}
			writeTencentJSON(t, w, map[string]any{"code": "OK", "data": map[string]any{"questions": questions}})
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
}

func loadTencentQuestionsFixture(t *testing.T) []map[string]any {
	t.Helper()
	data, err := os.ReadFile("testdata/questions.json")
	if err != nil {
		t.Fatal(err)
	}
	var questions []map[string]any
	if err := json.Unmarshal(data, &questions); err != nil {
		t.Fatal(err)
	}
	return questions
}

func writeTencentJSON(t *testing.T, w http.ResponseWriter, value any) {
	t.Helper()
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(value); err != nil {
		t.Fatal(err)
	}
}
