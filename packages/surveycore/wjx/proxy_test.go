package wjx

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync/atomic"
	"testing"
)

func TestPostFormUsesActiveProxy(t *testing.T) {
	var hits atomic.Int32
	proxy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		if !r.URL.IsAbs() || r.URL.Path != "/joinnew/processjq.ashx" {
			t.Fatalf("proxy request URL = %s", r.URL.String())
		}
		if err := r.ParseForm(); err != nil {
			t.Fatal(err)
		}
		if r.Form.Get("submitdata") != "1$1" {
			t.Fatalf("submitdata = %q", r.Form.Get("submitdata"))
		}
		_, _ = w.Write([]byte("10"))
	}))
	defer proxy.Close()

	body, err := (Runner{}).postForm(
		context.Background(),
		"http://www.wjx.cn/joinnew/processjq.ashx",
		"https://www.wjx.cn/vm/demo.aspx",
		url.Values{"submittype": {"1"}},
		url.Values{"submitdata": {"1$1"}},
		proxy.URL,
	)
	if err != nil {
		t.Fatal(err)
	}
	if body != "10" || hits.Load() != 1 {
		t.Fatalf("body = %q proxy hits = %d", body, hits.Load())
	}
}
