package credamo

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestParserParsesDetailQuestions(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/survey/noauth/detail/get/demoano" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if r.Header.Get("signature") == "" {
			t.Fatal("missing signature header")
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"success": true,
			"data": map[string]any{
				"surveyTitle": "Credamo 标题",
				"questions": []map[string]any{
					{
						"qstNo":        "Q1",
						"qstTitle":     "单选题",
						"questionType": 2,
						"selector":     1,
						"questionId":   "q1",
						"choices":      []map[string]any{{"display": "A"}, {"display": "B"}},
					},
					{
						"qstNo":        "Q2",
						"qstTitle":     "矩阵题",
						"questionType": 4,
						"questionId":   "q2",
						"choices":      []map[string]any{{"display": "行1"}, {"display": "行2"}},
						"answers":      []map[string]any{{"display": "满意"}, {"display": "不满意"}},
					},
				},
			},
		})
	}))
	defer server.Close()

	definition, err := (Parser{}).Parse(context.Background(), server.URL+"/s/demo_")
	if err != nil {
		t.Fatal(err)
	}
	if definition.Title != "Credamo 标题" {
		t.Fatalf("title = %q", definition.Title)
	}
	if len(definition.Questions) != 2 {
		t.Fatalf("question count = %d", len(definition.Questions))
	}
	if definition.Questions[0].TypeCode != "3" || definition.Questions[0].ProviderType != "single" {
		t.Fatalf("unexpected first question: %+v", definition.Questions[0])
	}
	if definition.Questions[1].TypeCode != "6" || len(definition.Questions[1].RowTexts) != 2 {
		t.Fatalf("unexpected matrix question: %+v", definition.Questions[1])
	}
}

func TestParserRejectsEmptyQuestions(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"success": true,
			"data": map[string]any{
				"surveyTitle": "空问卷",
				"questions":   []any{},
			},
		})
	}))
	defer server.Close()

	_, err := (Parser{}).Parse(context.Background(), server.URL+"/s/demo_")
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestNormalizeQuestionKinds(t *testing.T) {
	cases := map[string]string{
		"single":   "3",
		"multiple": "4",
		"dropdown": "7",
		"scale":    "5",
		"order":    "11",
		"matrix":   "6",
		"text":     "1",
	}
	for kind, want := range cases {
		got := normalizeQuestion(map[string]any{
			"question_num":  "Q1",
			"title":         "Q1",
			"question_kind": kind,
			"provider_type": kind,
			"option_texts":  []any{"A", "B"},
			"text_inputs":   0,
			"page":          1,
			"question_id":   "q1",
		}, 1)
		if got.TypeCode != want {
			t.Fatalf("%s type = %s, want %s", kind, got.TypeCode, want)
		}
	}
}
