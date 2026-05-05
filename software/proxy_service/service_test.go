package main

import (
	"testing"
	"time"
)

func TestFilterLeasesForConfigLockedDropsBlockedAndExpired(t *testing.T) {
	now := time.Now().Add(5 * time.Minute).UTC().Format(time.RFC3339)
	cfg := proxyConfig{OccupyMinute: 1}
	leases := []proxyLease{
		{Address: "http://1.1.1.1:8000", Poolable: true, ExpireAt: now, ExpireTS: parseExpireAtToTS(now)},
		{Address: "http://1.1.1.1:8000", Poolable: true, ExpireAt: now, ExpireTS: parseExpireAtToTS(now)},
		{Address: "http://2.2.2.2:8000", Poolable: false, ExpireAt: now, ExpireTS: parseExpireAtToTS(now)},
		{Address: "http://3.3.3.3:8000", Poolable: true, ExpireTS: float64(time.Now().Add(10 * time.Second).Unix())},
		{Address: "http://4.4.4.4:8000", Poolable: true, ExpireAt: now, ExpireTS: parseExpireAtToTS(now)},
	}
	cooldown := map[string]time.Time{
		"http://4.4.4.4:8000": time.Now().Add(2 * time.Minute),
	}
	successful := map[string]struct{}{
		"http://5.5.5.5:8000": {},
	}
	inUse := map[string]proxyLease{
		"Slot-1": {Address: "http://6.6.6.6:8000"},
	}

	filtered := filterLeasesForConfigLocked(leases, cfg, cooldown, successful, inUse)
	if len(filtered) != 1 {
		t.Fatalf("expected 1 lease, got %d: %#v", len(filtered), filtered)
	}
	if filtered[0].Address != "http://1.1.1.1:8000" {
		t.Fatalf("unexpected lease kept: %#v", filtered[0])
	}
}

func TestReleaseLeaseRequeuesWhenStillPoolable(t *testing.T) {
	svc := newPoolService("http://127.0.0.1:9010")
	lease := proxyLease{Address: "http://1.1.1.1:8000", Poolable: true}
	svc.inUseByThread["Slot-1"] = lease

	released := svc.releaseLease("Slot-1", true)
	if released == nil || released.Address != lease.Address {
		t.Fatalf("unexpected released lease: %#v", released)
	}
	if len(svc.pool) != 1 || svc.pool[0].Address != lease.Address {
		t.Fatalf("expected lease to return to pool, got %#v", svc.pool)
	}
}

func TestMarkSuccessAndMarkBadUpdateRuntimeSets(t *testing.T) {
	svc := newPoolService("http://127.0.0.1:9010")
	lease := proxyLease{Address: "http://1.1.1.1:8000", Poolable: true}
	svc.inUseByThread["Slot-1"] = lease
	svc.pool = []proxyLease{lease, {Address: "http://2.2.2.2:8000", Poolable: true}}

	svc.markSuccess("http://1.1.1.1:8000", "Slot-1")
	if _, ok := svc.successful["http://1.1.1.1:8000"]; !ok {
		t.Fatalf("expected successful set to contain lease")
	}
	if _, ok := svc.inUseByThread["Slot-1"]; ok {
		t.Fatalf("expected in-use lease to be cleared after success")
	}

	svc.markBad("http://2.2.2.2:8000", 180, "")
	if _, ok := svc.cooldownUntil["http://2.2.2.2:8000"]; !ok {
		t.Fatalf("expected cooldown set to contain bad lease")
	}
	for _, item := range svc.pool {
		if item.Address == "http://2.2.2.2:8000" {
			t.Fatalf("bad lease should have been removed from pool: %#v", svc.pool)
		}
	}
}
