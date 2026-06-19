package proxycore

import (
	"context"
	"testing"
)

func TestOfficialSessionManagerLoadsStoredSession(t *testing.T) {
	store := NewMemorySessionStore(RandomIPSession{
		DeviceID:       "stored-device",
		UserID:         42,
		RemainingQuota: 3,
		TotalQuota:     10,
		UsedQuota:      7,
		QuotaKnown:     true,
	})
	manager := NewOfficialSessionManager(OfficialSessionManagerOptions{
		Store:             store,
		DeviceIDGenerator: DeviceIDGeneratorFunc(func(context.Context) (string, error) { return "generated-device", nil }),
	})

	session, err := manager.EnsureLoaded(context.Background())
	if err != nil {
		t.Fatalf("EnsureLoaded() error = %v", err)
	}
	if session.DeviceID != "stored-device" || session.UserID != 42 {
		t.Fatalf("unexpected session: %#v", session)
	}
}

func TestOfficialSessionManagerGeneratesAndPersistsDeviceID(t *testing.T) {
	store := NewMemorySessionStore(RandomIPSession{})
	manager := NewOfficialSessionManager(OfficialSessionManagerOptions{
		Store:             store,
		DeviceIDGenerator: DeviceIDGeneratorFunc(func(context.Context) (string, error) { return "generated-device", nil }),
	})

	session, err := manager.EnsureLoaded(context.Background())
	if err != nil {
		t.Fatalf("EnsureLoaded() error = %v", err)
	}
	if session.DeviceID != "generated-device" {
		t.Fatalf("DeviceID = %q", session.DeviceID)
	}
	loaded, ok, err := store.LoadSession(context.Background())
	if err != nil || !ok || loaded.DeviceID != "generated-device" {
		t.Fatalf("stored session = %#v, %v, %v", loaded, ok, err)
	}
}

func TestOfficialSessionManagerAppliesPartialQuotaPayload(t *testing.T) {
	manager := NewOfficialSessionManager(OfficialSessionManagerOptions{
		InitialSession: RandomIPSession{
			DeviceID:       "device-1",
			UserID:         9,
			RemainingQuota: 8,
			TotalQuota:     10,
			UsedQuota:      2,
			QuotaKnown:     true,
		},
	})

	session, err := manager.ApplyQuotaPayload(context.Background(), map[string]any{"used_quota": "4"})
	if err != nil {
		t.Fatalf("ApplyQuotaPayload() error = %v", err)
	}
	if session.RemainingQuota != 6 || session.TotalQuota != 10 || session.UsedQuota != 4 || !session.QuotaKnown {
		t.Fatalf("unexpected session: %#v", session)
	}
}

func TestFormatQuotaValue(t *testing.T) {
	cases := map[any]string{
		"2.5000": "2.5",
		"3.0":    "3",
		"-1":     "0",
		"bad":    "0",
	}
	for input, want := range cases {
		if got := FormatQuotaValue(input); got != want {
			t.Fatalf("FormatQuotaValue(%v) = %q, want %q", input, got, want)
		}
	}
}
