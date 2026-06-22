package proxycore

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestHTTPFetcherFetchesAndParsesCustomAPI(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Test") != "ok" {
			t.Fatalf("missing header: %#v", r.Header)
		}
		_, _ = w.Write([]byte(`{"data":["1.1.1.1:8000","user:pass@2.2.2.2:9000"]}`))
	}))
	defer server.Close()

	fetcher, err := NewHTTPFetcher(HTTPFetcherOptions{
		Endpoint: server.URL,
		Headers:  map[string]string{"X-Test": "ok"},
		Source:   "api",
	})
	if err != nil {
		t.Fatal(err)
	}
	leases, err := fetcher.Fetch(context.Background(), 2)
	if err != nil {
		t.Fatal(err)
	}
	if len(leases) != 2 || leases[0].Address != "http://1.1.1.1:8000" || leases[0].Source != "api" {
		t.Fatalf("leases = %#v", leases)
	}
}

func TestHTTPFetcherParsesPlainTextPayload(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("1.1.1.1:8000\n1.1.1.1:8000\nhttp://2.2.2.2:9000"))
	}))
	defer server.Close()

	fetcher, err := NewHTTPFetcher(HTTPFetcherOptions{Endpoint: server.URL})
	if err != nil {
		t.Fatal(err)
	}
	leases, err := fetcher.Fetch(context.Background(), 2)
	if err != nil {
		t.Fatal(err)
	}
	if len(leases) != 2 || leases[1].Address != "http://2.2.2.2:9000" {
		t.Fatalf("leases = %#v", leases)
	}
}

func TestHTTPFetcherHonorsContextCancel(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		time.Sleep(100 * time.Millisecond)
		_, _ = w.Write([]byte(`{"data":["1.1.1.1:8000"]}`))
	}))
	defer server.Close()

	fetcher, err := NewHTTPFetcher(HTTPFetcherOptions{Endpoint: server.URL, Timeout: time.Second})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err = fetcher.Fetch(ctx, 1)
	if err == nil || !strings.Contains(err.Error(), "context canceled") {
		t.Fatalf("err = %v", err)
	}
}

func TestHTTPFetcherRejectsBadStatusAndMissingEndpoint(t *testing.T) {
	if _, err := NewHTTPFetcher(HTTPFetcherOptions{}); !errors.Is(err, ErrProxyUnavailable) {
		t.Fatalf("missing endpoint err = %v", err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer server.Close()
	fetcher, err := NewHTTPFetcher(HTTPFetcherOptions{Endpoint: server.URL})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = fetcher.Fetch(context.Background(), 1); !errors.Is(err, ErrProxyUnavailable) {
		t.Fatalf("bad status err = %v", err)
	}
}
