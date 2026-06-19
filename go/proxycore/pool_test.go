package proxycore

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"
)

func TestPoolFiltersAndSelectsLeases(t *testing.T) {
	now := time.Unix(100, 0)
	pool := NewPool(PoolOptions{
		RequiredTTL: 50 * time.Second,
		Now:         func() time.Time { return now },
	})
	pool.MarkSuccess("http://4.4.4.4:8000")
	pool.MarkCooldown("http://5.5.5.5:8000", 180*time.Second)

	merged := pool.Add([]ProxyLease{
		{Address: "1.1.1.1:8000", Poolable: true},
		{Address: "1.1.1.1:8000", Poolable: true},
		{Address: "2.2.2.2:8000", Poolable: false},
		{Address: "3.3.3.3:8000", Poolable: true, ExpireTS: float64(now.Add(10 * time.Second).Unix())},
		{Address: "http://4.4.4.4:8000", Poolable: true},
		{Address: "http://5.5.5.5:8000", Poolable: true},
		{Address: "6.6.6.6:8000", Poolable: true, ExpireTS: float64(now.Add(60 * time.Second).Unix())},
	})
	if merged != 2 {
		t.Fatalf("merged = %d, want 2", merged)
	}
	lease, err := pool.Acquire(context.Background(), "worker-1")
	if err != nil {
		t.Fatalf("Acquire() error = %v", err)
	}
	if lease.Address != "http://1.1.1.1:8000" {
		t.Fatalf("selected = %#v", lease)
	}
	lease, err = pool.Acquire(context.Background(), "worker-2")
	if err != nil {
		t.Fatalf("Acquire() second error = %v", err)
	}
	if lease.Address != "http://6.6.6.6:8000" {
		t.Fatalf("selected second = %#v", lease)
	}
}

func TestPoolSkipsInUseAndRestoresAfterRelease(t *testing.T) {
	pool := NewPool(PoolOptions{})
	pool.Add([]ProxyLease{
		{Address: "1.1.1.1:8000", Poolable: true},
		{Address: "2.2.2.2:8000", Poolable: true},
	})
	first, err := pool.Acquire(context.Background(), "worker-1")
	if err != nil {
		t.Fatalf("Acquire first error = %v", err)
	}
	second, err := pool.Acquire(context.Background(), "worker-2")
	if err != nil {
		t.Fatalf("Acquire second error = %v", err)
	}
	if first.Address == second.Address {
		t.Fatalf("same proxy selected twice: %q", first.Address)
	}
	if released, ok := pool.Release("worker-1"); !ok || released.Address != first.Address {
		t.Fatalf("Release() = %#v, %v", released, ok)
	}
}

func TestPoolCooldownExpires(t *testing.T) {
	now := time.Unix(100, 0)
	pool := NewPool(PoolOptions{Now: func() time.Time { return now }})
	pool.Add([]ProxyLease{{Address: "1.1.1.1:8000", Poolable: true}})
	pool.MarkCooldown("http://1.1.1.1:8000", 10*time.Second)
	if pool.Len() != 0 {
		t.Fatalf("cooldown proxy should be removed from pool")
	}
	now = now.Add(11 * time.Second)
	pool.Add([]ProxyLease{{Address: "1.1.1.1:8000", Poolable: true}})
	lease, err := pool.Acquire(context.Background(), "worker-1")
	if err != nil {
		t.Fatalf("Acquire after cooldown error = %v", err)
	}
	if lease.Address != "http://1.1.1.1:8000" {
		t.Fatalf("lease = %#v", lease)
	}
}

func TestPoolFetchesOnceForConcurrentAcquire(t *testing.T) {
	var mu sync.Mutex
	fetchCalls := 0
	fetcher := FetcherFunc(func(_ context.Context, expectedCount int) ([]ProxyLease, error) {
		mu.Lock()
		fetchCalls++
		mu.Unlock()
		time.Sleep(20 * time.Millisecond)
		leases := make([]ProxyLease, 0, expectedCount)
		for i := 1; i <= expectedCount; i++ {
			leases = append(leases, ProxyLease{Address: fmt.Sprintf("10.0.0.%d:8000", i), Poolable: true})
		}
		return leases, nil
	})
	pool := NewPool(PoolOptions{Fetcher: fetcher, MaxFetch: 4})

	const workers = 4
	var wg sync.WaitGroup
	results := make(chan string, workers)
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(index int) {
			defer wg.Done()
			lease, err := pool.Acquire(context.Background(), fmt.Sprintf("worker-%d", index))
			if err != nil {
				t.Errorf("Acquire(%d) error = %v", index, err)
				return
			}
			results <- lease.Address
		}(i)
	}
	wg.Wait()
	close(results)

	if fetchCalls != 1 {
		t.Fatalf("fetchCalls = %d, want 1", fetchCalls)
	}
	seen := map[string]struct{}{}
	for address := range results {
		if _, exists := seen[address]; exists {
			t.Fatalf("duplicate address selected: %s", address)
		}
		seen[address] = struct{}{}
	}
	if len(seen) != workers {
		t.Fatalf("selected %d proxies, want %d", len(seen), workers)
	}
}

func TestPoolFetchSelectsOneAndPoolsExtra(t *testing.T) {
	pool := NewPool(PoolOptions{
		Fetcher: FetcherFunc(func(_ context.Context, _ int) ([]ProxyLease, error) {
			return []ProxyLease{
				{Address: "1.1.1.1:8000", Poolable: true, Source: "api"},
				{Address: "2.2.2.2:8000", Poolable: true, Source: "api"},
			}, nil
		}),
		MaxFetch: 2,
	})
	lease, err := pool.Acquire(context.Background(), "worker-1")
	if err != nil {
		t.Fatalf("Acquire() error = %v", err)
	}
	if lease.Address != "http://1.1.1.1:8000" {
		t.Fatalf("lease = %#v", lease)
	}
	if pool.Len() != 1 {
		t.Fatalf("pool.Len() = %d, want 1", pool.Len())
	}
	next, err := pool.Acquire(context.Background(), "worker-2")
	if err != nil {
		t.Fatalf("Acquire next error = %v", err)
	}
	if next.Address != "http://2.2.2.2:8000" {
		t.Fatalf("next = %#v", next)
	}
}
