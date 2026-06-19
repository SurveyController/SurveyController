package proxycore

import (
	"context"
	"strings"
)

type OfficialFetcher struct {
	client   *OfficialClient
	minute   int
	pool     string
	area     string
	upstream string
	source   string
	maxFetch int
}

func NewOfficialFetcher(options OfficialFetcherOptions) *OfficialFetcher {
	source := strings.TrimSpace(options.Source)
	if source == "" {
		source = OfficialSourceDefault
	}
	maxFetch := options.MaxFetch
	if maxFetch <= 0 {
		maxFetch = 1
	}
	return &OfficialFetcher{
		client:   options.Client,
		minute:   options.Minute,
		pool:     options.Pool,
		area:     options.Area,
		upstream: options.Upstream,
		source:   source,
		maxFetch: maxFetch,
	}
}

func (f *OfficialFetcher) Fetch(ctx context.Context, expectedCount int) ([]ProxyLease, error) {
	if f.client == nil {
		return nil, ErrProxyUnavailable
	}
	if expectedCount <= 0 {
		expectedCount = 1
	}
	if f.maxFetch > 0 && expectedCount > f.maxFetch {
		expectedCount = f.maxFetch
	}
	result, err := f.client.ExtractProxy(ctx, OfficialExtractRequest{
		Minute:   f.minute,
		Pool:     f.pool,
		Area:     f.area,
		Num:      expectedCount,
		Upstream: f.upstream,
	})
	if err != nil {
		return nil, err
	}
	source := f.source
	if result.Provider == OfficialUpstreamBenefit {
		source = OfficialSourceBenefit
	} else if result.Provider == OfficialUpstreamDefault {
		source = OfficialSourceDefault
	}
	leases := make([]ProxyLease, 0, len(result.Items))
	for _, item := range result.Items {
		lease, ok := BuildOfficialProxyLease(item, source)
		if ok {
			leases = append(leases, lease)
		}
	}
	if len(leases) == 0 {
		return nil, ErrProxyUnavailable
	}
	return leases, nil
}
