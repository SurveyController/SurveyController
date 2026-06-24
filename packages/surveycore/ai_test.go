package surveycore

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestResolveAIEndpointHandlesExplicitAndLegacyURLs(t *testing.T) {
	protocol, endpoint, explicit, err := resolveAIEndpoint(" https://example.com/v1/chat/completions/ ", "auto")
	if err != nil {
		t.Fatal(err)
	}
	if protocol != aiProtocolChat || endpoint != "https://example.com/v1/chat/completions" || !explicit {
		t.Fatalf("endpoint = %q %q %v", protocol, endpoint, explicit)
	}
	protocol, endpoint, explicit, err = resolveAIEndpoint("https://example.com/v1", "Responses")
	if err != nil {
		t.Fatal(err)
	}
	if protocol != aiProtocolResponses || endpoint != "https://example.com/v1/responses" || explicit {
		t.Fatalf("endpoint = %q %q %v", protocol, endpoint, explicit)
	}
	if _, _, _, err := resolveAIEndpoint("https://example.com/v1/completions", "auto"); err == nil || !strings.Contains(err.Error(), "/completions") {
		t.Fatalf("legacy err = %v", err)
	}
}

func TestProviderAIReadsChatCompletionContentParts(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/chat/completions" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		var payload map[string]any
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatal(err)
		}
		if payload["model"] != "demo-model" {
			t.Fatalf("payload = %#v", payload)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"choices": []map[string]any{{
				"message": map[string]any{
					"content": []map[string]any{
						{"type": "text", "text": "第一句"},
						{"type": "output_text", "text": "第二句"},
					},
				},
			}},
		})
	}))
	defer server.Close()

	client := New()
	answers, err := client.callProviderAI(context.Background(), RuntimeConfig{
		AIMode:        "provider",
		AIProvider:    "custom",
		AIAPIKey:      "test-key",
		AIBaseURL:     server.URL + "/v1/chat/completions",
		AIModel:       "demo-model",
		AIAPIProtocol: "auto",
	}, AITextRequest{QuestionNum: 1, Title: "问题", BlankCount: 1})
	if err != nil {
		t.Fatal(err)
	}
	if len(answers) != 1 || answers[0] != "第一句\n第二句" {
		t.Fatalf("answers = %#v", answers)
	}
}

func TestProviderAIAutoFallsBackToResponsesOnEndpointMismatch(t *testing.T) {
	paths := make([]string, 0, 2)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		paths = append(paths, r.URL.Path)
		if r.URL.Path == "/v1/chat/completions" {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if r.URL.Path != "/v1/responses" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"output_text": "回退成功"})
	}))
	defer server.Close()

	client := New()
	answers, err := client.callProviderAI(context.Background(), RuntimeConfig{
		AIMode:        "provider",
		AIProvider:    "custom",
		AIAPIKey:      "test-key",
		AIBaseURL:     server.URL + "/v1",
		AIModel:       "demo-model",
		AIAPIProtocol: "auto",
	}, AITextRequest{QuestionNum: 1, Title: "问题", BlankCount: 1})
	if err != nil {
		t.Fatal(err)
	}
	if len(answers) != 1 || answers[0] != "回退成功" {
		t.Fatalf("answers = %#v", answers)
	}
	if len(paths) != 2 || paths[0] != "/v1/chat/completions" || paths[1] != "/v1/responses" {
		t.Fatalf("paths = %#v", paths)
	}
}

func TestProviderAICustomRequiresBaseURLAndModel(t *testing.T) {
	client := New()
	_, err := client.callProviderAI(context.Background(), RuntimeConfig{
		AIMode:     "provider",
		AIProvider: "custom",
		AIAPIKey:   "test-key",
		AIModel:    "demo-model",
	}, AITextRequest{QuestionNum: 1, Title: "问题", BlankCount: 1})
	if err == nil || !strings.Contains(err.Error(), "Base URL") {
		t.Fatalf("err = %v", err)
	}
	_, err = client.callProviderAI(context.Background(), RuntimeConfig{
		AIMode:     "provider",
		AIProvider: "custom",
		AIAPIKey:   "test-key",
		AIBaseURL:  "https://example.com/v1",
	}, AITextRequest{QuestionNum: 1, Title: "问题", BlankCount: 1})
	if err == nil || !strings.Contains(err.Error(), "模型") {
		t.Fatalf("err = %v", err)
	}
}
