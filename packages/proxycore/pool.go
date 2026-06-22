package proxycore

import (
	"context"
	"strings"
	"sync"
	"time"
)

type PoolOptions struct {
	Fetcher     Fetcher
	MaxFetch    int
	RequiredTTL time.Duration
	Now         func() time.Time
}

type Pool struct {
	mu          sync.Mutex
	fetchMu     sync.Mutex
	leases      []ProxyLease
	inUse       map[string]ProxyLease
	successful  map[string]struct{}
	cooldown    map[string]time.Time
	fetcher     Fetcher
	maxFetch    int
	requiredTTL time.Duration
	now         func() time.Time
}

func NewPool(options PoolOptions) *Pool {
	now := options.Now
	if now == nil {
		now = time.Now
	}
	maxFetch := options.MaxFetch
	if maxFetch <= 0 {
		maxFetch = 1
	}
	return &Pool{
		inUse:       make(map[string]ProxyLease),
		successful:  make(map[string]struct{}),
		cooldown:    make(map[string]time.Time),
		fetcher:     options.Fetcher,
		maxFetch:    maxFetch,
		requiredTTL: options.RequiredTTL,
		now:         now,
	}
}

func (p *Pool) Add(fetched []ProxyLease) int {
	p.mu.Lock()
	defer p.mu.Unlock()
	before := len(p.leases)
	p.mergeLocked(fetched)
	return len(p.leases) - before
}

func (p *Pool) Acquire(ctx context.Context, owner string) (ProxyLease, error) {
	if lease, ok := p.tryPop(owner); ok {
		return lease, nil
	}
	p.fetchMu.Lock()
	defer p.fetchMu.Unlock()

	if lease, ok := p.tryPop(owner); ok {
		return lease, nil
	}
	if p.fetcher == nil {
		return ProxyLease{}, ErrProxyUnavailable
	}
	fetched, err := p.fetcher.Fetch(ctx, p.maxFetch)
	if err != nil {
		return ProxyLease{}, err
	}
	p.Add(fetched)
	if lease, ok := p.tryPop(owner); ok {
		return lease, nil
	}
	return ProxyLease{}, ErrProxyUnavailable
}

func (p *Pool) Release(owner string) (ProxyLease, bool) {
	key := strings.TrimSpace(owner)
	if key == "" {
		return ProxyLease{}, false
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	lease, ok := p.inUse[key]
	if ok {
		delete(p.inUse, key)
	}
	return lease, ok
}

func (p *Pool) MarkSuccess(proxyAddress string) bool {
	normalized := strings.TrimSpace(proxyAddress)
	if normalized == "" {
		return false
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	before := len(p.successful)
	p.successful[normalized] = struct{}{}
	return len(p.successful) != before
}

func (p *Pool) MarkCooldown(proxyAddress string, cooldownFor time.Duration) {
	normalized := strings.TrimSpace(proxyAddress)
	if normalized == "" || cooldownFor <= 0 {
		return
	}
	until := p.now().Add(cooldownFor)
	p.mu.Lock()
	defer p.mu.Unlock()
	if previous, ok := p.cooldown[normalized]; !ok || until.After(previous) {
		p.cooldown[normalized] = until
	}
	p.discardAddressLocked(normalized)
}

func (p *Pool) Len() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.purgeExpiredCooldownsLocked()
	return len(p.leases)
}

func (p *Pool) InUseLen() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return len(p.inUse)
}

func (p *Pool) tryPop(owner string) (ProxyLease, bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.popAvailableLocked(owner)
}

func (p *Pool) popAvailableLocked(owner string) (ProxyLease, bool) {
	p.purgeExpiredCooldownsLocked()
	blocked := p.blockedAddressesLocked(owner)
	kept := make([]ProxyLease, 0, len(p.leases))
	seen := make(map[string]struct{}, len(p.leases))
	var selected ProxyLease
	selectedFound := false

	for _, raw := range p.leases {
		lease, ok := normalizeLease(raw)
		if !ok || !lease.Poolable {
			continue
		}
		if _, duplicated := seen[lease.Address]; duplicated {
			continue
		}
		seen[lease.Address] = struct{}{}
		if p.isCooldownLocked(lease.Address) {
			continue
		}
		if !ProxyLeaseHasSufficientTTL(lease, p.requiredTTL, p.now()) {
			continue
		}
		if _, unavailable := blocked[lease.Address]; unavailable {
			kept = append(kept, lease)
			continue
		}
		if !selectedFound {
			selected = lease
			selectedFound = true
			continue
		}
		kept = append(kept, lease)
	}
	p.leases = kept
	if !selectedFound {
		return ProxyLease{}, false
	}
	if key := strings.TrimSpace(owner); key != "" {
		p.inUse[key] = selected
	}
	return selected, true
}

func (p *Pool) mergeLocked(fetched []ProxyLease) {
	p.purgeExpiredCooldownsLocked()
	existing := p.blockedAddressesLocked("")
	for _, lease := range p.leases {
		normalized, ok := normalizeLease(lease)
		if ok {
			existing[normalized.Address] = struct{}{}
		}
	}
	for _, raw := range fetched {
		lease, ok := normalizeLease(raw)
		if !ok || !lease.Poolable {
			continue
		}
		if !ProxyLeaseHasSufficientTTL(lease, p.requiredTTL, p.now()) {
			continue
		}
		if p.isCooldownLocked(lease.Address) {
			continue
		}
		if _, duplicated := existing[lease.Address]; duplicated {
			continue
		}
		p.leases = append(p.leases, lease)
		existing[lease.Address] = struct{}{}
	}
}

func (p *Pool) blockedAddressesLocked(excludeOwner string) map[string]struct{} {
	blocked := make(map[string]struct{}, len(p.inUse)+len(p.successful))
	excluded := strings.TrimSpace(excludeOwner)
	for owner, lease := range p.inUse {
		if excluded != "" && strings.TrimSpace(owner) == excluded {
			continue
		}
		if address := strings.TrimSpace(lease.Address); address != "" {
			blocked[address] = struct{}{}
		}
	}
	for address := range p.successful {
		blocked[address] = struct{}{}
	}
	return blocked
}

func (p *Pool) purgeExpiredCooldownsLocked() {
	now := p.now()
	for address, until := range p.cooldown {
		if !until.After(now) {
			delete(p.cooldown, address)
		}
	}
}

func (p *Pool) isCooldownLocked(proxyAddress string) bool {
	until, ok := p.cooldown[proxyAddress]
	return ok && until.After(p.now())
}

func (p *Pool) discardAddressLocked(proxyAddress string) {
	retained := p.leases[:0]
	for _, lease := range p.leases {
		if lease.Address != proxyAddress {
			retained = append(retained, lease)
		}
	}
	p.leases = retained
}

func normalizeLease(lease ProxyLease) (ProxyLease, bool) {
	normalized, ok := NormalizeProxyAddress(lease.Address)
	if !ok {
		return ProxyLease{}, false
	}
	lease.Address = normalized
	if lease.Source == "" {
		lease.Source = defaultProxySource
	}
	return lease, true
}
