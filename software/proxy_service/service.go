package main

import (
	"errors"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

type poolService struct {
	baseURL    string
	httpClient *http.Client

	mu            sync.Mutex
	config        proxyConfig
	pool          []proxyLease
	inUseByThread map[string]proxyLease
	successful    map[string]struct{}
	cooldownUntil map[string]time.Time
	healthCache   map[string]healthCacheEntry
}

func newPoolService(baseURL string) *poolService {
	return &poolService{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: proxyStatusTimeoutSeconds * time.Second,
		},
		config: proxyConfig{
			Source:       sourceDefault,
			CustomAPIURL: "",
			AreaCode:     "",
			OccupyMinute: 1,
		},
		pool:          make([]proxyLease, 0),
		inUseByThread: make(map[string]proxyLease),
		successful:    make(map[string]struct{}),
		cooldownUntil: make(map[string]time.Time),
		healthCache:   make(map[string]healthCacheEntry),
	}
}

func (svc *poolService) applyConfig(cfg proxyConfig) proxyConfig {
	svc.mu.Lock()
	defer svc.mu.Unlock()
	cfg.Source = normalizeProxySource(cfg.Source)
	cfg.CustomAPIURL = strings.TrimSpace(cfg.CustomAPIURL)
	cfg.AreaCode = normalizeAreaCode(cfg.AreaCode)
	if cfg.OccupyMinute <= 0 {
		cfg.OccupyMinute = 1
	}
	svc.config = cfg
	svc.pool = filterLeasesForConfigLocked(svc.pool, svc.config, svc.cooldownUntil, svc.successful, svc.inUseByThread)
	return svc.config
}

func filterLeasesForConfigLocked(
	leases []proxyLease,
	cfg proxyConfig,
	cooldown map[string]time.Time,
	successful map[string]struct{},
	inUse map[string]proxyLease,
) []proxyLease {
	now := time.Now()
	for key, until := range cooldown {
		if !until.After(now) {
			delete(cooldown, key)
		}
	}
	kept := make([]proxyLease, 0, len(leases))
	seen := make(map[string]struct{}, len(leases))
	requiredTTL := requiredTTLSeconds(cfg)
	blocked := make(map[string]struct{}, len(successful)+len(inUse))
	for address := range successful {
		blocked[address] = struct{}{}
	}
	for _, lease := range inUse {
		blocked[lease.Address] = struct{}{}
	}
	for _, lease := range leases {
		if lease.Address == "" || !lease.Poolable {
			continue
		}
		if _, ok := seen[lease.Address]; ok {
			continue
		}
		if until, ok := cooldown[lease.Address]; ok && until.After(now) {
			continue
		}
		if !hasSufficientTTL(&lease, requiredTTL) {
			continue
		}
		if _, ok := blocked[lease.Address]; ok {
			continue
		}
		seen[lease.Address] = struct{}{}
		kept = append(kept, lease)
	}
	return kept
}

func (svc *poolService) acquireLease(threadName string, wait bool) (*proxyLease, error) {
	threadName = strings.TrimSpace(threadName)
	if threadName == "" {
		return nil, errors.New("thread_name 不能为空")
	}
	deadline := time.Now().Add(waitPollInterval)
	for {
		svc.mu.Lock()
		if lease := svc.popAvailableLeaseLocked(); lease != nil {
			svc.inUseByThread[threadName] = *lease
			svc.mu.Unlock()
			return lease, nil
		}
		svc.mu.Unlock()

		if err := svc.prefetch(1); err != nil && !wait {
			return nil, err
		}

		svc.mu.Lock()
		if lease := svc.popAvailableLeaseLocked(); lease != nil {
			svc.inUseByThread[threadName] = *lease
			svc.mu.Unlock()
			return lease, nil
		}
		svc.mu.Unlock()

		if !wait {
			return nil, nil
		}
		if time.Now().After(deadline) {
			deadline = time.Now().Add(waitPollInterval)
		}
		time.Sleep(waitPollInterval)
	}
}

func (svc *poolService) popAvailableLeaseLocked() *proxyLease {
	svc.pool = filterLeasesForConfigLocked(svc.pool, svc.config, svc.cooldownUntil, svc.successful, svc.inUseByThread)
	if len(svc.pool) == 0 {
		return nil
	}
	lease := svc.pool[0]
	svc.pool = append([]proxyLease{}, svc.pool[1:]...)
	return &lease
}

func (svc *poolService) releaseLease(threadName string, requeue bool) *proxyLease {
	threadName = strings.TrimSpace(threadName)
	if threadName == "" {
		return nil
	}
	svc.mu.Lock()
	defer svc.mu.Unlock()
	lease, ok := svc.inUseByThread[threadName]
	if !ok {
		return nil
	}
	delete(svc.inUseByThread, threadName)
	if requeue && lease.Poolable {
		if _, done := svc.successful[lease.Address]; !done {
			if until, cooling := svc.cooldownUntil[lease.Address]; !cooling || !until.After(time.Now()) {
				svc.pool = append(svc.pool, lease)
			}
		}
	}
	return &lease
}

func (svc *poolService) markSuccess(proxyAddress string, threadName string) {
	proxyAddress = normalizeProxyAddress(proxyAddress)
	threadName = strings.TrimSpace(threadName)
	svc.mu.Lock()
	defer svc.mu.Unlock()
	if proxyAddress != "" {
		svc.successful[proxyAddress] = struct{}{}
	}
	if threadName != "" {
		delete(svc.inUseByThread, threadName)
	}
	svc.pool = filterLeasesForConfigLocked(svc.pool, svc.config, svc.cooldownUntil, svc.successful, svc.inUseByThread)
}

func (svc *poolService) markBad(proxyAddress string, cooldownSeconds float64, threadName string) {
	proxyAddress = normalizeProxyAddress(proxyAddress)
	threadName = strings.TrimSpace(threadName)
	if proxyAddress == "" {
		return
	}
	if cooldownSeconds <= 0 {
		cooldownSeconds = 180
	}
	svc.mu.Lock()
	defer svc.mu.Unlock()
	svc.cooldownUntil[proxyAddress] = time.Now().Add(time.Duration(cooldownSeconds * float64(time.Second)))
	delete(svc.healthCache, proxyAddress)
	if threadName != "" {
		delete(svc.inUseByThread, threadName)
	}
	filtered := make([]proxyLease, 0, len(svc.pool))
	for _, lease := range svc.pool {
		if lease.Address != proxyAddress {
			filtered = append(filtered, lease)
		}
	}
	svc.pool = filtered
}

func (svc *poolService) prefetch(expectedCount int) error {
	expectedCount = minInt(maxInt(expectedCount, 1), maxProxyBatchSize)
	fetched, err := svc.fetchProxyBatch(expectedCount)
	if err != nil {
		return err
	}
	svc.mu.Lock()
	defer svc.mu.Unlock()
	existing := make(map[string]struct{}, len(svc.pool)+len(svc.successful)+len(svc.inUseByThread))
	for _, lease := range svc.pool {
		existing[lease.Address] = struct{}{}
	}
	for address := range svc.successful {
		existing[address] = struct{}{}
	}
	for _, lease := range svc.inUseByThread {
		existing[lease.Address] = struct{}{}
	}
	for _, lease := range fetched {
		if lease.Address == "" {
			continue
		}
		if _, ok := existing[lease.Address]; ok {
			continue
		}
		if until, cooling := svc.cooldownUntil[lease.Address]; cooling && until.After(time.Now()) {
			continue
		}
		if !hasSufficientTTL(&lease, requiredTTLSeconds(svc.config)) {
			continue
		}
		if lease.Poolable {
			svc.pool = append(svc.pool, lease)
			existing[lease.Address] = struct{}{}
		}
	}
	svc.pool = filterLeasesForConfigLocked(svc.pool, svc.config, svc.cooldownUntil, svc.successful, svc.inUseByThread)
	return nil
}

func (svc *poolService) snapshotConfig() proxyConfig {
	svc.mu.Lock()
	defer svc.mu.Unlock()
	return svc.config
}

func (svc *poolService) checkHealth(proxyAddress string, skipForOfficial bool) bool {
	proxyAddress = normalizeProxyAddress(proxyAddress)
	if proxyAddress == "" {
		return false
	}
	cfg := svc.snapshotConfig()
	if skipForOfficial && normalizeProxySource(cfg.Source) != sourceCustom {
		return true
	}
	now := time.Now()
	svc.mu.Lock()
	if entry, ok := svc.healthCache[proxyAddress]; ok && entry.ExpireAt.After(now) {
		result := entry.Responsive
		svc.mu.Unlock()
		return result
	}
	svc.mu.Unlock()

	responsive := probeProxyHealth(proxyAddress)

	svc.mu.Lock()
	svc.healthCache[proxyAddress] = healthCacheEntry{
		Responsive: responsive,
		ExpireAt:   time.Now().Add(healthCacheTTL),
	}
	svc.mu.Unlock()
	return responsive
}

func (svc *poolService) status() statusResponse {
	svc.mu.Lock()
	defer svc.mu.Unlock()
	now := time.Now()
	cooldownSize := 0
	for address, until := range svc.cooldownUntil {
		if until.After(now) {
			cooldownSize++
		} else {
			delete(svc.cooldownUntil, address)
		}
	}
	return statusResponse{
		OK:             true,
		PID:            os.Getpid(),
		Config:         svc.config,
		PoolSize:       len(svc.pool),
		InUseSize:      len(svc.inUseByThread),
		CooldownSize:   cooldownSize,
		SuccessfulSize: len(svc.successful),
	}
}
