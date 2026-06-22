package proxycore

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestOfficialClientActivateTrialSendsDeviceIDAndStoresQuota(t *testing.T) {
	var receivedDeviceID string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedDeviceID = r.Header.Get("X-Device-ID")
		if r.URL.Path != "/trial" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		writeJSON(t, w, map[string]any{
			"user_id":         33,
			"remaining_quota": 7,
			"total_quota":     10,
			"used_quota":      3,
		})
	}))
	defer server.Close()

	store := NewMemorySessionStore(RandomIPSession{DeviceID: "device-1"})
	manager := NewOfficialSessionManager(OfficialSessionManagerOptions{Store: store})
	client := NewOfficialClient(OfficialClientOptions{
		TrialEndpoint:  server.URL + "/trial",
		SessionManager: manager,
	})

	session, err := client.ActivateTrial(context.Background())
	if err != nil {
		t.Fatalf("ActivateTrial() error = %v", err)
	}
	if receivedDeviceID != "device-1" {
		t.Fatalf("X-Device-ID = %q", receivedDeviceID)
	}
	if session.UserID != 33 || session.RemainingQuota != 7 || !session.QuotaKnown {
		t.Fatalf("unexpected session: %#v", session)
	}
}

func TestOfficialClientExtractProxyBuildsRequestAndUpdatesQuota(t *testing.T) {
	var requestBody map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/extract" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		if r.Header.Get("X-Device-ID") != "device-2" {
			t.Fatalf("X-Device-ID = %q", r.Header.Get("X-Device-ID"))
		}
		if err := json.NewDecoder(r.Body).Decode(&requestBody); err != nil {
			t.Fatalf("decode body: %v", err)
		}
		writeJSON(t, w, map[string]any{
			"provider":         "default",
			"requested_count":  2,
			"returned_count":   2,
			"quota_cost_total": "4.5",
			"remaining_quota":  5,
			"total_quota":      10,
			"used_quota":       5,
			"items": []map[string]any{
				{
					"host":      "8.8.8.8",
					"port":      9000,
					"account":   "u",
					"password":  "p",
					"expire_at": "2099-01-01T00:00:00+00:00",
				},
				{
					"host":     "8.8.4.4",
					"port":     9001,
					"account":  "u2",
					"password": "p2",
				},
			},
		})
	}))
	defer server.Close()

	manager := NewOfficialSessionManager(OfficialSessionManagerOptions{
		InitialSession: RandomIPSession{DeviceID: "device-2", UserID: 55, TotalQuota: 10, QuotaKnown: true},
	})
	client := NewOfficialClient(OfficialClientOptions{
		ExtractEndpoint: server.URL + "/extract",
		SessionManager:  manager,
	})

	result, err := client.ExtractProxy(context.Background(), OfficialExtractRequest{
		Minute:   3,
		Pool:     OfficialPoolQuality,
		Area:     "110100",
		Num:      2,
		Upstream: OfficialUpstreamBenefit,
	})
	if err != nil {
		t.Fatalf("ExtractProxy() error = %v", err)
	}
	wantBody := map[string]any{
		"user_id":  float64(55),
		"minute":   float64(3),
		"pool":     OfficialPoolQuality,
		"area":     "110100",
		"num":      float64(2),
		"upstream": OfficialUpstreamBenefit,
	}
	for key, want := range wantBody {
		if requestBody[key] != want {
			t.Fatalf("body[%s] = %#v, want %#v; body=%#v", key, requestBody[key], want, requestBody)
		}
	}
	if len(result.Items) != 2 || result.Items[0].Host != "8.8.8.8" || result.Items[1].ExpireAt != "" {
		t.Fatalf("unexpected result: %#v", result)
	}
	if result.QuotaCostTotal != 4.5 || result.Quota.RemainingQuota != 5 {
		t.Fatalf("unexpected quota: %#v", result)
	}
}

func TestOfficialFetcherConvertsExtractResultToLeases(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(t, w, map[string]any{
			"provider":        "benefit",
			"remaining_quota": 9,
			"total_quota":     10,
			"used_quota":      1,
			"items": []map[string]any{
				{
					"host":      "1.1.1.1",
					"port":      8000,
					"account":   "u",
					"password":  "p",
					"expire_at": "2099-01-01T00:00:00+00:00",
				},
				{
					"host":     "2.2.2.2",
					"port":     8001,
					"account":  "u2",
					"password": "p2",
				},
			},
		})
	}))
	defer server.Close()

	client := NewOfficialClient(OfficialClientOptions{
		ExtractEndpoint: server.URL,
		SessionManager: NewOfficialSessionManager(OfficialSessionManagerOptions{
			InitialSession: RandomIPSession{DeviceID: "device-3", UserID: 66, TotalQuota: 10, QuotaKnown: true},
		}),
	})
	fetcher := NewOfficialFetcher(OfficialFetcherOptions{
		Client:   client,
		Minute:   1,
		Pool:     OfficialPoolQuality,
		Upstream: OfficialUpstreamBenefit,
		MaxFetch: 4,
	})

	leases, err := fetcher.Fetch(context.Background(), 2)
	if err != nil {
		t.Fatalf("Fetch() error = %v", err)
	}
	if len(leases) != 2 {
		t.Fatalf("len(leases) = %d", len(leases))
	}
	if leases[0].Address != "http://u:p@1.1.1.1:8000" || leases[0].Source != OfficialSourceBenefit || !leases[0].Poolable {
		t.Fatalf("unexpected first lease: %#v", leases[0])
	}
	if leases[1].Poolable {
		t.Fatalf("lease without expire_at should not be poolable: %#v", leases[1])
	}
}

func TestOfficialClientErrorPayloadIncludesRetryAfter(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Retry-After", "3")
		w.WriteHeader(http.StatusTooManyRequests)
		writeJSON(t, w, map[string]any{"detail": "token_rate_limited", "retry_after_seconds": 9})
	}))
	defer server.Close()

	client := NewOfficialClient(OfficialClientOptions{
		TrialEndpoint: server.URL,
		SessionManager: NewOfficialSessionManager(OfficialSessionManagerOptions{
			InitialSession: RandomIPSession{DeviceID: "device-4"},
		}),
	})

	_, err := client.ActivateTrial(context.Background())
	got, ok := err.(RandomIPError)
	if !ok {
		t.Fatalf("err = %#v", err)
	}
	if got.Detail != "token_rate_limited" || got.StatusCode != http.StatusTooManyRequests || got.RetryAfterSeconds != 9 {
		t.Fatalf("unexpected error: %#v", got)
	}
}

func TestOfficialClientRedeemCardUpdatesQuota(t *testing.T) {
	var requestBody map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := json.NewDecoder(r.Body).Decode(&requestBody); err != nil {
			t.Fatalf("decode body: %v", err)
		}
		writeJSON(t, w, map[string]any{
			"redeemed":        true,
			"card_quota":      400,
			"detail":          "redeem_card_redeemed",
			"remaining_quota": 401,
			"total_quota":     402,
			"used_quota":      1,
		})
	}))
	defer server.Close()

	client := NewOfficialClient(OfficialClientOptions{
		RedeemEndpoint: server.URL,
		SessionManager: NewOfficialSessionManager(OfficialSessionManagerOptions{
			InitialSession: RandomIPSession{DeviceID: "device-5", UserID: 77, TotalQuota: 1, QuotaKnown: true},
		}),
	})

	result, err := client.RedeemCard(context.Background(), " abc123 ")
	if err != nil {
		t.Fatalf("RedeemCard() error = %v", err)
	}
	if requestBody["user_id"] != float64(77) || requestBody["card_code"] != "abc123" {
		t.Fatalf("request body = %#v", requestBody)
	}
	if !result.Redeemed || result.CardQuota != 400 || result.Quota.RemainingQuota != 401 {
		t.Fatalf("unexpected result: %#v", result)
	}
}

func writeJSON(t *testing.T, w http.ResponseWriter, payload any) {
	t.Helper()
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		t.Fatalf("encode response: %v", err)
	}
}
