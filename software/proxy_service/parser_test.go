package main

import "testing"

func TestParseProxyPayloadSupportsNestedJSONAndDedup(t *testing.T) {
	body := []byte(`{"data":[{"ip":"1.1.1.1","port":"8000"},{"proxy":"http://1.1.1.1:8000"},"2.2.2.2:9000"]}`)
	addresses, err := parseProxyPayload(body)
	if err != nil {
		t.Fatalf("parseProxyPayload returned error: %v", err)
	}
	if len(addresses) != 2 {
		t.Fatalf("expected 2 unique addresses, got %d: %#v", len(addresses), addresses)
	}
	if addresses[0] != "1.1.1.1:8000" || addresses[1] != "2.2.2.2:9000" {
		t.Fatalf("unexpected addresses: %#v", addresses)
	}
}

func TestExtractProxyFromDictSupportsAuthFields(t *testing.T) {
	address := extractProxyFromDict(map[string]any{
		"host":     "3.3.3.3",
		"port":     "8080",
		"username": "user",
		"password": "pass",
	})
	if address != "user:pass@3.3.3.3:8080" {
		t.Fatalf("unexpected address: %s", address)
	}
}
