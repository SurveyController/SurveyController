package proxycore

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"
)

type QuotaSnapshot struct {
	RemainingQuota float64
	TotalQuota     float64
	UsedQuota      float64
	QuotaKnown     bool
}

func NormalizeQuotaState(remainingQuota any, totalQuota any, usedQuota any, defaultTotalQuota float64) (float64, float64, float64) {
	hasRemaining := remainingQuota != nil
	hasUsed := usedQuota != nil
	remaining := 0.0
	if hasRemaining {
		remaining = nonNegativeFloat(remainingQuota, 0)
	}
	total := nonNegativeFloat(totalQuota, defaultTotalQuota)
	if hasUsed {
		used := nonNegativeFloat(usedQuota, 0)
		total = math.Max(total, used)
		return math.Max(0, total-used), total, used
	}
	if hasRemaining {
		total = math.Max(total, remaining)
		return remaining, total, math.Max(0, total-remaining)
	}
	total = math.Max(0, total)
	return total, total, 0
}

func FormatQuotaValue(value any) string {
	parsed, ok := optionalNonNegativeFloat(value)
	if !ok {
		return "0"
	}
	if math.Trunc(parsed) == parsed {
		return strconv.FormatInt(int64(parsed), 10)
	}
	text := strconv.FormatFloat(parsed, 'f', -1, 64)
	return strings.TrimRight(strings.TrimRight(text, "0"), ".")
}

func QuotaCostByMinute(minute int) int {
	switch minute {
	case 1:
		return 1
	case 3:
		return 2
	case 5:
		return 3
	case 10:
		return 5
	case 15:
		return 8
	case 30:
		return 20
	default:
		return 1
	}
}

func normalizeQuotaSnapshot(session RandomIPSession) QuotaSnapshot {
	remaining, total, used := NormalizeQuotaState(session.RemainingQuota, session.TotalQuota, session.UsedQuota, 0)
	return QuotaSnapshot{
		RemainingQuota: remaining,
		TotalQuota:     total,
		UsedQuota:      used,
		QuotaKnown:     session.QuotaKnown,
	}
}

func normalizeSession(session RandomIPSession) RandomIPSession {
	remaining, total, used := NormalizeQuotaState(session.RemainingQuota, session.TotalQuota, session.UsedQuota, 0)
	session.DeviceID = strings.TrimSpace(session.DeviceID)
	session.RemainingQuota = remaining
	session.TotalQuota = total
	session.UsedQuota = used
	session.QuotaKnown = normalizeQuotaKnown(session.UserID, total, used, session.QuotaKnown)
	return session
}

func normalizeQuotaKnown(userID int, totalQuota float64, usedQuota float64, quotaKnown bool) bool {
	if userID <= 0 {
		return false
	}
	if !quotaKnown {
		return false
	}
	return totalQuota > 0 || usedQuota > 0
}

func resolveQuotaFromPayload(payload map[string]any, fallback RandomIPSession) (QuotaSnapshot, bool) {
	fallbackQuota := normalizeQuotaSnapshot(fallback)
	remaining, hasRemaining := optionalPayloadQuota(payload, "remaining_quota")
	total, hasTotal := optionalPayloadQuota(payload, "total_quota")
	used, hasUsed := optionalPayloadQuota(payload, "used_quota")
	validCount := 0
	for _, ok := range []bool{hasRemaining, hasTotal, hasUsed} {
		if ok {
			validCount++
		}
	}
	var candidate QuotaSnapshot
	hasCandidate := false
	if validCount >= 2 {
		candidate.RemainingQuota, candidate.TotalQuota, candidate.UsedQuota = NormalizeQuotaState(optionalAny(remaining, hasRemaining), optionalAny(total, hasTotal), optionalAny(used, hasUsed), fallbackQuota.TotalQuota)
		hasCandidate = true
	} else if validCount == 1 && fallback.QuotaKnown {
		switch {
		case hasRemaining:
			candidate.RemainingQuota, candidate.TotalQuota, candidate.UsedQuota = NormalizeQuotaState(remaining, fallbackQuota.TotalQuota, nil, fallbackQuota.TotalQuota)
		case hasTotal:
			candidate.RemainingQuota, candidate.TotalQuota, candidate.UsedQuota = NormalizeQuotaState(nil, total, fallbackQuota.UsedQuota, total)
		case hasUsed:
			candidate.RemainingQuota, candidate.TotalQuota, candidate.UsedQuota = NormalizeQuotaState(nil, fallbackQuota.TotalQuota, used, fallbackQuota.TotalQuota)
		}
		hasCandidate = true
	}
	if hasCandidate && (candidate.TotalQuota > 0 || candidate.UsedQuota > 0) {
		candidate.QuotaKnown = true
		return candidate, true
	}
	return fallbackQuota, false
}

func optionalAny(value float64, ok bool) any {
	if !ok {
		return nil
	}
	return value
}

func optionalPayloadQuota(payload map[string]any, key string) (float64, bool) {
	value, exists := payload[key]
	if !exists {
		return 0, false
	}
	return optionalNonNegativeFloat(value)
}

func nonNegativeFloat(value any, fallback float64) float64 {
	parsed, ok := optionalNonNegativeFloat(value)
	if !ok {
		parsed = fallback
	}
	if parsed < 0 || math.IsNaN(parsed) || math.IsInf(parsed, 0) {
		return 0
	}
	return parsed
}

func optionalNonNegativeFloat(value any) (float64, bool) {
	switch item := value.(type) {
	case nil:
		return 0, false
	case float64:
		if item < 0 || math.IsNaN(item) || math.IsInf(item, 0) {
			return 0, false
		}
		return item, true
	case float32:
		return optionalNonNegativeFloat(float64(item))
	case int:
		return optionalNonNegativeFloat(float64(item))
	case int64:
		return optionalNonNegativeFloat(float64(item))
	case jsonNumber:
		return optionalNonNegativeFloat(item.String())
	case string:
		text := strings.TrimSpace(item)
		if text == "" {
			return 0, false
		}
		parsed, err := strconv.ParseFloat(text, 64)
		if err != nil || parsed < 0 || math.IsNaN(parsed) || math.IsInf(parsed, 0) {
			return 0, false
		}
		return parsed, true
	default:
		text := strings.TrimSpace(fmt.Sprint(item))
		if text == "" || text == "<nil>" {
			return 0, false
		}
		parsed, err := strconv.ParseFloat(text, 64)
		if err != nil || parsed < 0 || math.IsNaN(parsed) || math.IsInf(parsed, 0) {
			return 0, false
		}
		return parsed, true
	}
}

type jsonNumber interface {
	String() string
}

func positiveInt(value any, fallback int) int {
	parsed, ok := intValue(value)
	if !ok || parsed <= 0 {
		return fallback
	}
	return parsed
}

func nonNegativeInt(value any, fallback int) int {
	parsed, ok := intValue(value)
	if !ok || parsed < 0 {
		return max(0, fallback)
	}
	return parsed
}

func intValue(value any) (int, bool) {
	switch item := value.(type) {
	case int:
		return item, true
	case int64:
		return int(item), true
	case float64:
		return int(item), true
	case string:
		text := strings.TrimSpace(item)
		if text == "" {
			return 0, false
		}
		parsed, err := strconv.Atoi(text)
		return parsed, err == nil
	default:
		return 0, false
	}
}

func extractTimeout(num int) time.Duration {
	requestNum := max(1, num)
	timeout := 10*time.Second + time.Duration(requestNum-1)*2*time.Second
	return min(timeout, 60*time.Second)
}
