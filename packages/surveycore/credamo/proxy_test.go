package credamo

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

func TestSubmitRequestsUseActiveProxy(t *testing.T) {
	var hits atomic.Int32
	proxy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		if !r.URL.IsAbs() {
			t.Fatalf("proxy request URL = %s", r.URL.String())
		}
		switch r.URL.Path {
		case "/v1/survey/answer/noauth/init/demo":
			writeJSON(t, w, map[string]any{
				"success": true,
				"data": map[string]any{
					"answerToken": "token",
					"timestamp":   1700000000000,
				},
			})
		case "/v1/survey/answer/noauth/save":
			writeJSON(t, w, map[string]any{"success": true, "data": map[string]any{"ok": true}})
		default:
			t.Fatalf("unexpected proxy path: %s", r.URL.Path)
		}
	}))
	defer proxy.Close()

	runner := Runner{}
	initData, err := runner.initAnswer(context.Background(), "http://credamo.test", "demo", proxy.URL)
	if err != nil {
		t.Fatal(err)
	}
	if err := runner.saveAnswers(context.Background(), "http://credamo.test", "demo", initData, map[string]any{"answerQstList": []any{}}, proxy.URL); err != nil {
		t.Fatal(err)
	}
	if hits.Load() != 2 {
		t.Fatalf("proxy hits = %d", hits.Load())
	}
}

func writeJSON(t *testing.T, w http.ResponseWriter, value any) {
	t.Helper()
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(value); err != nil {
		t.Fatal(err)
	}
}
