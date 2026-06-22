package proxycore

import (
	"errors"
	"net/http"
)

const (
	DefaultOfficialTrialEndpoint   = "https://api-wjx.hungrym0.com/api/auth/trial"
	DefaultOfficialExtractEndpoint = "https://api-wjx.hungrym0.com/api/ip/extract"
	DefaultOfficialBonusEndpoint   = "https://api-wjx.hungrym0.com/api/bonus"
	DefaultOfficialRedeemEndpoint  = "https://api-wjx.hungrym0.com/api/cards/redeem"

	OfficialSourceDefault = "default"
	OfficialSourceBenefit = "benefit"

	OfficialUpstreamDefault = "default"
	OfficialUpstreamBenefit = "benefit"

	OfficialPoolOrdinary = "ordinary"
	OfficialPoolQuality  = "quality"
)

var (
	ErrNotAuthenticated = errors.New("official proxy session is not authenticated")
	ErrInvalidResponse  = errors.New("official proxy response is invalid")
)

type RandomIPError struct {
	Detail            string
	StatusCode        int
	RetryAfterSeconds int
}

func (e RandomIPError) Error() string {
	if e.Detail == "" {
		return "official proxy request failed"
	}
	return e.Detail
}

type RandomIPSession struct {
	DeviceID       string
	UserID         int
	RemainingQuota float64
	TotalQuota     float64
	UsedQuota      float64
	QuotaKnown     bool
}

func (s RandomIPSession) Authenticated() bool {
	return s.UserID > 0
}

func (s RandomIPSession) HasUnknownQuota() bool {
	return s.Authenticated() && !s.QuotaKnown
}

func (s RandomIPSession) QuotaExhausted() bool {
	if !s.Authenticated() || !s.QuotaKnown {
		return false
	}
	return s.TotalQuota > 0 && s.UsedQuota >= s.TotalQuota
}

type OfficialProxyItem struct {
	Host     string
	Port     int
	Account  string
	Password string
	ExpireAt string
}

type OfficialExtractRequest struct {
	Minute   int
	Pool     string
	Area     string
	Num      int
	Upstream string
}

type OfficialExtractResult struct {
	Items          []OfficialProxyItem
	RequestedCount int
	ReturnedCount  int
	Provider       string
	QuotaCost      float64
	QuotaCostTotal float64
	Quota          QuotaSnapshot
}

type OfficialClientOptions struct {
	TrialEndpoint   string
	ExtractEndpoint string
	BonusEndpoint   string
	RedeemEndpoint  string
	HTTPClient      *http.Client
	Headers         map[string]string
	SessionManager  *OfficialSessionManager
}

type OfficialFetcherOptions struct {
	Client   *OfficialClient
	Minute   int
	Pool     string
	Area     string
	Upstream string
	Source   string
	MaxFetch int
}

type BonusResult struct {
	Claimed    bool
	BonusQuota float64
	Detail     string
	Quota      QuotaSnapshot
}

type RedeemResult struct {
	Redeemed  bool
	CardQuota float64
	Detail    string
	Quota     QuotaSnapshot
}
