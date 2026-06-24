package model

import (
	"math/rand"
	"strings"
)

const (
	userAgentCategoryWechat = "wechat"
	userAgentCategoryMobile = "mobile"
	userAgentCategoryPC     = "pc"
)

type UserAgentProfile struct {
	Category  string
	PresetKey string
	UserAgent string
	Label     string
}

var defaultRandomUARatios = map[string]int{
	userAgentCategoryWechat: 33,
	userAgentCategoryMobile: 33,
	userAgentCategoryPC:     34,
}

var userAgentPresets = map[string]UserAgentProfile{
	"wechat_android": {
		Category:  userAgentCategoryWechat,
		PresetKey: "wechat_android",
		Label:     "安卓微信端",
		UserAgent: "Mozilla/5.0 (Linux; Android 16; Pixel 8 Build/BP22.250124.009; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/121.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.43.2460(0x28002B3B) Process/appbrand0 WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
	},
	"mobile_android": {
		Category:  userAgentCategoryMobile,
		PresetKey: "mobile_android",
		Label:     "安卓手机浏览器",
		UserAgent: "Mozilla/5.0 (Linux; Android 16; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
	},
	"pc_web": {
		Category:  userAgentCategoryPC,
		PresetKey: "pc_web",
		Label:     "电脑网页端",
		UserAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
	},
}

func SelectUserAgentFromRatios(ratios map[string]int) (UserAgentProfile, bool) {
	normalized := normalizeRandomUARatios(ratios)
	total := 0
	for _, category := range []string{userAgentCategoryWechat, userAgentCategoryMobile, userAgentCategoryPC} {
		total += normalized[category]
	}
	if total <= 0 {
		return UserAgentProfile{}, false
	}
	pick := rand.Intn(total)
	acc := 0
	for _, category := range []string{userAgentCategoryWechat, userAgentCategoryMobile, userAgentCategoryPC} {
		acc += normalized[category]
		if pick >= acc {
			continue
		}
		switch category {
		case userAgentCategoryWechat:
			return userAgentPresets["wechat_android"], true
		case userAgentCategoryMobile:
			return userAgentPresets["mobile_android"], true
		default:
			return userAgentPresets["pc_web"], true
		}
	}
	return UserAgentProfile{}, false
}

func RuntimeUserAgent(cfg *RuntimeConfig) string {
	if cfg == nil || !cfg.RandomUAEnabled {
		return ""
	}
	profile, ok := SelectUserAgentFromRatios(cfg.RandomUARatios)
	if !ok {
		return ""
	}
	return strings.TrimSpace(profile.UserAgent)
}

func SampleAnswerDurationSeconds(durationRange [2]int, defaultUnconfiguredSeconds int) int {
	minDelay, maxDelay := normalizeRuntimeRange(durationRange, defaultUnconfiguredSeconds)
	if minDelay == 0 && maxDelay == 0 {
		return 0
	}
	if minDelay == maxDelay {
		base := maxDelay
		jitter := maxInt(5, base/5)
		minDelay = maxInt(0, base-jitter)
		maxDelay = base + jitter
	}
	if maxDelay <= minDelay {
		return minDelay
	}
	center := float64(minDelay+maxDelay) / 2
	stdDev := float64(maxDelay-minDelay) / 6
	value := int(rand.NormFloat64()*stdDev + center)
	if value < minDelay {
		return minDelay
	}
	if value > maxDelay {
		return maxDelay
	}
	return value
}

func SampleSubmitIntervalSeconds(intervalRange [2]int) int {
	minDelay, maxDelay := normalizeRuntimeRange(intervalRange, 0)
	if maxDelay <= 0 {
		return 0
	}
	if maxDelay <= minDelay {
		return minDelay
	}
	return minDelay + rand.Intn(maxDelay-minDelay+1)
}

func normalizeRandomUARatios(ratios map[string]int) map[string]int {
	if len(ratios) == 0 {
		return cloneDefaultRandomUARatios()
	}
	result := map[string]int{}
	sum := 0
	for _, category := range []string{userAgentCategoryWechat, userAgentCategoryMobile, userAgentCategoryPC} {
		value := ratios[category]
		if value < 0 || value > 100 {
			return cloneDefaultRandomUARatios()
		}
		result[category] = value
		sum += value
	}
	if sum != 100 {
		return cloneDefaultRandomUARatios()
	}
	return result
}

func cloneDefaultRandomUARatios() map[string]int {
	return map[string]int{
		userAgentCategoryWechat: defaultRandomUARatios[userAgentCategoryWechat],
		userAgentCategoryMobile: defaultRandomUARatios[userAgentCategoryMobile],
		userAgentCategoryPC:     defaultRandomUARatios[userAgentCategoryPC],
	}
}

func normalizeRuntimeRange(value [2]int, defaultUnconfiguredSeconds int) (int, int) {
	left := maxInt(0, value[0])
	right := maxInt(0, value[1])
	if left == 0 && right == 0 && defaultUnconfiguredSeconds > 0 {
		left = defaultUnconfiguredSeconds
		right = defaultUnconfiguredSeconds
	}
	if right < left {
		right = left
	}
	return left, right
}

func maxInt(left int, right int) int {
	if left > right {
		return left
	}
	return right
}
