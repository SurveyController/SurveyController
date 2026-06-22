package proxycore

import (
	"context"
	"os"
	"testing"
	"time"
)

func TestLiveCustomProxyAPI(t *testing.T) {
	endpoint := os.Getenv("SC_PROXY_API_URL")
	if endpoint == "" {
		t.Skip("SC_PROXY_API_URL not set")
	}
	fetcher, err := NewHTTPFetcher(HTTPFetcherOptions{
		Endpoint: endpoint,
		Timeout:  20 * time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	leases, err := fetcher.Fetch(context.Background(), 1)
	if err != nil {
		t.Fatal(err)
	}
	if len(leases) == 0 || leases[0].Address == "" {
		t.Fatalf("leases = %#v", leases)
	}
}
