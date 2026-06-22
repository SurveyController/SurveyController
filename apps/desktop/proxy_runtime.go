package main

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"surveycontroller/proxycore"
	"surveycontroller/surveycore"
)

type proxyRuntime struct {
	mu     sync.Mutex
	key    string
	pool   *proxycore.Pool
	status ProxyStatus
}

func newProxyRuntime() *proxyRuntime {
	return &proxyRuntime{}
}

func (r *proxyRuntime) statusSnapshot() ProxyStatus {
	r.mu.Lock()
	defer r.mu.Unlock()
	status := r.status
	if status.Source == "" {
		status.Source = proxycore.OfficialSourceDefault
	}
	status.RemainingQuota = proxycore.FormatQuotaValue(status.Quota.RemainingQuota)
	status.TotalQuota = proxycore.FormatQuotaValue(status.Quota.TotalQuota)
	status.QuotaKnown = status.Quota.QuotaKnown
	if r.pool != nil {
		status.Available = r.pool.Len()
		status.InUse = r.pool.InUseLen()
	}
	return status
}

func (r *proxyRuntime) executionOptions(ctx context.Context, cfg surveycore.RuntimeConfig) (surveycore.ExecutionOptions, error) {
	options := surveycore.ExecutionOptionsFromConfig(&cfg)
	source := normalizeDesktopProxySource(cfg.ProxySource)
	if !cfg.RandomIPEnabled {
		r.updateStatus("", nil, ProxyStatus{
			RandomIPEnabled: false,
			Source:          source,
			Message:         "未启用",
		})
		return options, nil
	}

	switch source {
	case proxycore.DefaultCustomProxySource:
		manager, err := r.customLeaseManager(ctx, cfg, source, options)
		if err != nil {
			return options, err
		}
		options.LeaseManager = manager
		return options, nil
	case proxycore.OfficialSourceDefault, proxycore.OfficialSourceBenefit:
		r.updateStatus(proxyRuntimeKey(source, ""), nil, ProxyStatus{
			RandomIPEnabled: true,
			Source:          source,
			Message:         "官方代理源未接入",
		})
		return options, fmt.Errorf("%w: 官方随机 IP 源尚未接入桌面端", surveycore.ErrUnsupportedOperation)
	default:
		r.updateStatus(proxyRuntimeKey(source, ""), nil, ProxyStatus{
			RandomIPEnabled: true,
			Source:          source,
			Message:         "代理源不可用",
		})
		return options, fmt.Errorf("%w: 未知代理源 %q", surveycore.ErrInvalidConfig, source)
	}
}

func (r *proxyRuntime) customLeaseManager(_ context.Context, cfg surveycore.RuntimeConfig, source string, options surveycore.ExecutionOptions) (surveycore.LeaseManager, error) {
	endpoint := strings.TrimSpace(cfg.CustomProxyAPI)
	key := proxyRuntimeKey(source, endpoint)
	if endpoint == "" {
		r.updateStatus(key, nil, ProxyStatus{
			RandomIPEnabled: true,
			Source:          source,
			Message:         "自定义代理 API 为空",
		})
		return nil, fmt.Errorf("%w: 自定义代理 API 为空", surveycore.ErrInvalidConfig)
	}

	r.mu.Lock()
	defer r.mu.Unlock()
	if r.pool == nil || r.key != key {
		fetcher, err := proxycore.NewHTTPFetcher(proxycore.HTTPFetcherOptions{
			Endpoint: endpoint,
			Source:   source,
		})
		if err != nil {
			r.key = key
			r.pool = nil
			r.status = ProxyStatus{
				RandomIPEnabled: true,
				Source:          source,
				Message:         "自定义代理 API 不可用",
			}
			return nil, err
		}
		r.pool = proxycore.NewPool(proxycore.PoolOptions{
			Fetcher:  fetcher,
			MaxFetch: maxInt(1, options.Threads),
		})
		r.key = key
	}
	r.status = ProxyStatus{
		RandomIPEnabled: true,
		Source:          source,
		Message:         "自定义代理已连接",
	}
	return proxyLeaseManager{pool: r.pool}, nil
}

func (r *proxyRuntime) updateStatus(key string, pool *proxycore.Pool, status ProxyStatus) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.key = key
	r.pool = pool
	r.status = status
}

type proxyLeaseManager struct {
	pool *proxycore.Pool
}

func (m proxyLeaseManager) Acquire(ctx context.Context, owner string) (surveycore.ExecutionLease, error) {
	if m.pool == nil {
		return surveycore.ExecutionLease{}, proxycore.ErrProxyUnavailable
	}
	lease, err := m.pool.Acquire(ctx, owner)
	if err != nil {
		return surveycore.ExecutionLease{}, err
	}
	return surveycore.ExecutionLease{Address: lease.Address, Source: lease.Source}, nil
}

func (m proxyLeaseManager) Release(owner string) (surveycore.ExecutionLease, bool) {
	if m.pool == nil {
		return surveycore.ExecutionLease{}, false
	}
	lease, ok := m.pool.Release(owner)
	return surveycore.ExecutionLease{Address: lease.Address, Source: lease.Source}, ok
}

func (m proxyLeaseManager) MarkSuccess(proxyAddress string) bool {
	if m.pool == nil {
		return false
	}
	return m.pool.MarkSuccess(proxyAddress)
}

func (m proxyLeaseManager) MarkCooldown(proxyAddress string, cooldownFor time.Duration) {
	if m.pool == nil {
		return
	}
	m.pool.MarkCooldown(proxyAddress, cooldownFor)
}

func normalizeDesktopProxySource(source string) string {
	switch strings.ToLower(strings.TrimSpace(source)) {
	case "", proxycore.OfficialSourceDefault:
		return proxycore.OfficialSourceDefault
	case proxycore.OfficialSourceBenefit, "福利", "限时福利":
		return proxycore.OfficialSourceBenefit
	case proxycore.DefaultCustomProxySource, "自定义":
		return proxycore.DefaultCustomProxySource
	default:
		return strings.ToLower(strings.TrimSpace(source))
	}
}

func proxyRuntimeKey(source string, endpoint string) string {
	return source + "\n" + strings.TrimSpace(endpoint)
}

func maxInt(left int, right int) int {
	if left > right {
		return left
	}
	return right
}
