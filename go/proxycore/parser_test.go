package proxycore

import (
	"errors"
	"testing"
)

func TestParseProxyPayloadNestedAndDeduplicates(t *testing.T) {
	payload := []byte(`{
		"items": [
			{"ip": "1.1.1.1", "port": "8000", "account": "u", "password": "p"},
			"http://2.2.2.2:9000",
			{"nested": {"proxy": "u:p@1.1.1.1:8000"}}
		]
	}`)
	proxies, err := ParseProxyPayload(payload)
	if err != nil {
		t.Fatalf("ParseProxyPayload() error = %v", err)
	}
	want := []string{"u:p@1.1.1.1:8000", "2.2.2.2:9000"}
	if len(proxies) != len(want) {
		t.Fatalf("len(proxies) = %d, want %d: %#v", len(proxies), len(want), proxies)
	}
	for i := range want {
		if proxies[i] != want[i] {
			t.Fatalf("proxies[%d] = %q, want %q", i, proxies[i], want[i])
		}
	}
}

func TestParseProxyPayloadErrors(t *testing.T) {
	if _, err := ParseProxyPayload([]byte(`{`)); err == nil {
		t.Fatal("bad JSON should fail")
	}
	if _, err := ParseProxyPayload([]byte(`{"items":[]}`)); !errors.Is(err, ErrNoProxyAddress) {
		t.Fatalf("empty payload err = %v", err)
	}
}

func TestParseProxyLeases(t *testing.T) {
	leases, err := ParseProxyLeases([]byte(`{"data":["3.3.3.3:7000"]}`), "custom")
	if err != nil {
		t.Fatalf("ParseProxyLeases() error = %v", err)
	}
	if len(leases) != 1 || leases[0].Address != "http://3.3.3.3:7000" || leases[0].Source != "custom" {
		t.Fatalf("unexpected leases: %#v", leases)
	}
}
