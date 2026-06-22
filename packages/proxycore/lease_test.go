package proxycore

import (
	"testing"
	"time"
)

func TestNormalizeProxyAddressAndMask(t *testing.T) {
	normalized, ok := NormalizeProxyAddress(" 1.1.1.1:8000 ")
	if !ok || normalized != "http://1.1.1.1:8000" {
		t.Fatalf("NormalizeProxyAddress() = %q, %v", normalized, ok)
	}
	normalized, ok = NormalizeProxyAddress("https://1.1.1.1:8000")
	if !ok || normalized != "https://1.1.1.1:8000" {
		t.Fatalf("NormalizeProxyAddress() = %q, %v", normalized, ok)
	}
	if _, ok = NormalizeProxyAddress("   "); ok {
		t.Fatal("empty proxy should not normalize")
	}
	if got := MaskProxyForLog("http://user:pass@1.1.1.1:8000"); got != "1.1.1.1:8000" {
		t.Fatalf("MaskProxyForLog() = %q", got)
	}
	if got := MaskProxyForLog("http://user:pass@[2001:db8::1]:8080"); got != "[2001:db8::1]:8080" {
		t.Fatalf("MaskProxyForLog(ipv6) = %q", got)
	}
}

func TestBuildProxyLeaseAndTTL(t *testing.T) {
	lease, ok := BuildProxyLease("1.1.1.1:8000", "2099-01-01T00:00:00+00:00", true, "")
	if !ok {
		t.Fatal("BuildProxyLease failed")
	}
	if lease.Address != "http://1.1.1.1:8000" || lease.Source != defaultProxySource || lease.ExpireTS <= 0 {
		t.Fatalf("unexpected lease: %#v", lease)
	}
	now := time.Unix(100, 0)
	if !ProxyLeaseHasSufficientTTL(ProxyLease{Address: "http://1.1.1.1:8000"}, 24*time.Hour, now) {
		t.Fatal("lease without expire_ts should be treated as usable")
	}
	if !ProxyLeaseHasSufficientTTL(ProxyLease{Address: "http://1.1.1.1:8000", ExpireTS: 200}, 99*time.Second, now) {
		t.Fatal("lease should have sufficient ttl")
	}
	if ProxyLeaseHasSufficientTTL(ProxyLease{Address: "http://1.1.1.1:8000", ExpireTS: 120}, 30*time.Second, now) {
		t.Fatal("lease should not have sufficient ttl")
	}
	if ProxyLeaseHasSufficientTTL(ProxyLease{}, 0, now) {
		t.Fatal("empty lease should be unusable")
	}
}
