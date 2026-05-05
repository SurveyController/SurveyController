package main

import "time"

type proxyConfig struct {
	Source       string `json:"source"`
	CustomAPIURL string `json:"custom_api_url"`
	AreaCode     string `json:"area_code"`
	OccupyMinute int    `json:"occupy_minute"`
}

type proxyLease struct {
	Address  string  `json:"address"`
	ExpireAt string  `json:"expire_at"`
	ExpireTS float64 `json:"expire_ts"`
	Poolable bool    `json:"poolable"`
	Source   string  `json:"source"`
}

type acquireRequest struct {
	ThreadName string `json:"thread_name"`
	Wait       bool   `json:"wait"`
}

type releaseRequest struct {
	ThreadName string `json:"thread_name"`
	Requeue    bool   `json:"requeue"`
}

type addressRequest struct {
	ThreadName   string `json:"thread_name"`
	ProxyAddress string `json:"proxy_address"`
}

type markBadRequest struct {
	ThreadName      string  `json:"thread_name"`
	ProxyAddress    string  `json:"proxy_address"`
	CooldownSeconds float64 `json:"cooldown_seconds"`
}

type healthCheckRequest struct {
	ProxyAddress    string `json:"proxy_address"`
	SkipForOfficial bool   `json:"skip_for_official"`
}

type prefetchRequest struct {
	ExpectedCount int `json:"expected_count"`
}

type acquireResponse struct {
	Lease *proxyLease `json:"lease"`
}

type healthResponse struct {
	Responsive bool `json:"responsive"`
}

type statusResponse struct {
	OK             bool        `json:"ok"`
	PID            int         `json:"pid"`
	Config         proxyConfig `json:"config"`
	PoolSize       int         `json:"pool_size"`
	InUseSize      int         `json:"in_use_size"`
	CooldownSize   int         `json:"cooldown_size"`
	SuccessfulSize int         `json:"successful_size"`
}

type errorResponse struct {
	Error string `json:"error"`
}

type upstreamError struct {
	Message    string
	StatusCode int
}

type authError struct {
	Detail     string
	StatusCode int
}

type healthCacheEntry struct {
	Responsive bool
	ExpireAt   time.Time
}

type sessionSnapshot struct {
	Authenticated bool `json:"authenticated"`
	UserID        int  `json:"user_id"`
}
