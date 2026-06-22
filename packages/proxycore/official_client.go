package proxycore

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type OfficialClient struct {
	trialEndpoint   string
	extractEndpoint string
	bonusEndpoint   string
	redeemEndpoint  string
	httpClient      *http.Client
	headers         map[string]string
	sessionManager  *OfficialSessionManager
}

func NewOfficialClient(options OfficialClientOptions) *OfficialClient {
	httpClient := options.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 10 * time.Second}
	}
	manager := options.SessionManager
	if manager == nil {
		manager = NewOfficialSessionManager(OfficialSessionManagerOptions{})
	}
	return &OfficialClient{
		trialEndpoint:   endpointOrDefault(options.TrialEndpoint, DefaultOfficialTrialEndpoint),
		extractEndpoint: endpointOrDefault(options.ExtractEndpoint, DefaultOfficialExtractEndpoint),
		bonusEndpoint:   endpointOrDefault(options.BonusEndpoint, DefaultOfficialBonusEndpoint),
		redeemEndpoint:  endpointOrDefault(options.RedeemEndpoint, DefaultOfficialRedeemEndpoint),
		httpClient:      httpClient,
		headers:         cloneHeaders(options.Headers),
		sessionManager:  manager,
	}
}

func (c *OfficialClient) SessionManager() *OfficialSessionManager {
	return c.sessionManager
}

func (c *OfficialClient) ActivateTrial(ctx context.Context) (RandomIPSession, error) {
	session, err := c.sessionManager.EnsureLoaded(ctx)
	if err != nil {
		return RandomIPSession{}, err
	}
	payload, err := c.postJSON(ctx, c.trialEndpoint, map[string]any{}, 10*time.Second)
	if err != nil {
		return RandomIPSession{}, err
	}
	parsed, err := parseSessionPayload(payload, session.DeviceID, session)
	if err != nil {
		return RandomIPSession{}, err
	}
	return c.sessionManager.SetSession(ctx, parsed)
}

func (c *OfficialClient) SyncQuota(ctx context.Context) (QuotaSnapshot, error) {
	session, err := c.sessionManager.RequireAuthenticated(ctx)
	if err != nil {
		return QuotaSnapshot{}, err
	}
	payload, err := c.postJSON(ctx, c.trialEndpoint, map[string]any{}, 10*time.Second)
	if err != nil {
		return QuotaSnapshot{}, err
	}
	parsed, err := parseSessionPayload(payload, session.DeviceID, session)
	if err != nil {
		return QuotaSnapshot{}, err
	}
	updated, err := c.sessionManager.SetSession(ctx, parsed)
	if err != nil {
		return QuotaSnapshot{}, err
	}
	return normalizeQuotaSnapshot(updated), nil
}

func (c *OfficialClient) ExtractProxy(ctx context.Context, request OfficialExtractRequest) (OfficialExtractResult, error) {
	session, err := c.sessionManager.RequireAuthenticated(ctx)
	if err != nil {
		return OfficialExtractResult{}, err
	}
	request = normalizeExtractRequest(request)
	body := map[string]any{
		"user_id": int(session.UserID),
		"minute":  request.Minute,
		"pool":    request.Pool,
	}
	if request.Upstream != "" {
		body["upstream"] = request.Upstream
	}
	if request.Num > 1 {
		body["num"] = request.Num
	}
	if request.Area != "" {
		body["area"] = request.Area
	}
	payload, err := c.postJSON(ctx, c.extractEndpoint, body, extractTimeout(request.Num))
	if err != nil {
		return OfficialExtractResult{}, err
	}
	return c.parseExtractPayload(ctx, payload, request)
}

func (c *OfficialClient) ClaimBonus(ctx context.Context, bonusCode string) (BonusResult, error) {
	session, err := c.sessionManager.RequireAuthenticated(ctx)
	if err != nil {
		return BonusResult{}, err
	}
	code := strings.TrimSpace(bonusCode)
	if code == "" {
		code = "fuck-you-hacker"
	}
	payload, err := c.postJSON(ctx, c.bonusEndpoint, map[string]any{
		"user_id":    session.UserID,
		"bonus_code": code,
	}, 10*time.Second)
	if err != nil {
		return BonusResult{}, err
	}
	updated, err := c.sessionManager.ApplyQuotaPayload(ctx, payload)
	if err != nil {
		return BonusResult{}, err
	}
	return BonusResult{
		Claimed:    boolValue(payload["claimed"]),
		BonusQuota: nonNegativeFloat(payload["bonus_quota"], 0),
		Detail:     strings.TrimSpace(fmt.Sprint(payload["detail"])),
		Quota:      normalizeQuotaSnapshot(updated),
	}, nil
}

func (c *OfficialClient) RedeemCard(ctx context.Context, cardCode string) (RedeemResult, error) {
	session, err := c.sessionManager.RequireAuthenticated(ctx)
	if err != nil {
		return RedeemResult{}, err
	}
	payload, err := c.postJSON(ctx, c.redeemEndpoint, map[string]any{
		"user_id":   session.UserID,
		"card_code": strings.TrimSpace(cardCode),
	}, 10*time.Second)
	if err != nil {
		return RedeemResult{}, err
	}
	updated, err := c.sessionManager.ApplyQuotaPayload(ctx, payload)
	if err != nil {
		return RedeemResult{}, err
	}
	return RedeemResult{
		Redeemed:  boolValue(payload["redeemed"]),
		CardQuota: nonNegativeFloat(payload["card_quota"], 0),
		Detail:    strings.TrimSpace(fmt.Sprint(payload["detail"])),
		Quota:     normalizeQuotaSnapshot(updated),
	}, nil
}

func (c *OfficialClient) postJSON(ctx context.Context, endpoint string, body map[string]any, timeout time.Duration) (map[string]any, error) {
	session, err := c.sessionManager.EnsureLoaded(ctx)
	if err != nil {
		return nil, err
	}
	rawBody, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	reqCtx := ctx
	var cancel context.CancelFunc
	if timeout > 0 {
		reqCtx, cancel = context.WithTimeout(ctx, timeout)
		defer cancel()
	}
	request, err := http.NewRequestWithContext(reqCtx, http.MethodPost, endpoint, bytes.NewReader(rawBody))
	if err != nil {
		return nil, err
	}
	for key, value := range defaultOfficialHeaders() {
		request.Header.Set(key, value)
	}
	for key, value := range c.headers {
		request.Header.Set(key, value)
	}
	request.Header.Set("Content-Type", "application/json")
	if session.DeviceID != "" {
		request.Header.Set("X-Device-ID", session.DeviceID)
	}
	response, err := c.httpClient.Do(request)
	if err != nil {
		return nil, RandomIPError{Detail: "network_error:" + err.Error()}
	}
	defer response.Body.Close()
	responseBody, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, RandomIPError{Detail: "network_error:" + err.Error(), StatusCode: response.StatusCode}
	}
	if response.StatusCode != http.StatusOK {
		return nil, parseErrorPayload(response, responseBody)
	}
	var payload map[string]any
	if err := json.Unmarshal(responseBody, &payload); err != nil {
		return nil, RandomIPError{Detail: "invalid_response:" + err.Error(), StatusCode: response.StatusCode}
	}
	if payload == nil {
		return nil, RandomIPError{Detail: "invalid_response", StatusCode: response.StatusCode}
	}
	return payload, nil
}
