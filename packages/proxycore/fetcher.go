package proxycore

import (
	"context"
	"errors"
)

var ErrProxyUnavailable = errors.New("proxy unavailable")

type Fetcher interface {
	Fetch(ctx context.Context, expectedCount int) ([]ProxyLease, error)
}

type FetcherFunc func(ctx context.Context, expectedCount int) ([]ProxyLease, error)

func (fn FetcherFunc) Fetch(ctx context.Context, expectedCount int) ([]ProxyLease, error) {
	return fn(ctx, expectedCount)
}
