package main

import (
	"regexp"
	"time"
)

const (
	sourceDefault = "default"
	sourceBenefit = "benefit"
	sourceCustom  = "custom"

	upstreamDefault = "default"
	upstreamBenefit = "idiot"

	proxyStatusTimeoutSeconds = 10
	proxyHealthCheckTimeout   = 8 * time.Second
	proxyHealthCheckURL       = "https://www.baidu.com/"
	proxyTTLGraceSeconds      = 20
	maxProxyBatchSize         = 80
	healthCacheTTL            = 20 * time.Second
	serverReadTimeout         = 15 * time.Second
	serverWriteTimeout        = 15 * time.Second
	serverIdleTimeout         = 30 * time.Second
	waitPollInterval          = 300 * time.Millisecond
)

var (
	ipPortPattern = regexp.MustCompile(`(?:https?://)?(?:([^\s:@/,]+):([^\s:@/,]+)@)?((?:\d{1,3}\.){3}\d{1,3}):(\d{2,5})`)
	fatalPatterns = []struct {
		pattern *regexp.Regexp
		userMsg string
	}{
		{regexp.MustCompile(`白名单`), "请先添加当前IP到代理商白名单"},
		{regexp.MustCompile(`secret.*密匙错误`), "API密钥错误，请检查配置"},
		{regexp.MustCompile(`套餐余量不足`), "套餐余量不足，请充值"},
		{regexp.MustCompile(`套餐已过期`), "套餐已过期，请续费"},
		{regexp.MustCompile(`套餐被禁用`), "套餐已被禁用，请联系代理商"},
		{regexp.MustCompile(`身份未认证`), "请先完成实名认证"},
		{regexp.MustCompile(`用户被禁用`), "账号已被禁用，请联系代理商"},
	}
	ordinaryPoolProvinceCodes = map[string]struct{}{
		"110000": {}, "120000": {}, "130000": {}, "140000": {}, "150000": {},
		"210000": {}, "220000": {}, "230000": {}, "320000": {}, "330000": {},
		"340000": {}, "350000": {}, "360000": {}, "370000": {}, "410000": {},
		"420000": {}, "430000": {}, "440000": {}, "460000": {}, "500000": {},
		"510000": {}, "610000": {}, "620000": {}, "640000": {},
	}
)
