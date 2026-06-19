package credamo

import (
	"crypto/sha1"
	"fmt"
	"math/rand"
	"strconv"
	"strings"
	"time"
)

const (
	cipher             = "P96D0A7D0M8C3R2D0M1"
	randomChars        = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"
	defaultUserAgent   = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
	requestTimeoutSecs = 30
)

func requestHeaders(origin string, shortURL string, userAgent string, answerToken string) map[string]string {
	if strings.TrimSpace(userAgent) == "" {
		userAgent = defaultUserAgent
	}
	headers := map[string]string{
		"User-Agent":      userAgent,
		"Accept":          "application/json, text/plain, */*",
		"Accept-Language": "zh-CN,zh;q=0.9",
		"Referer":         answerPageURL(origin, shortURL),
	}
	for key, value := range signatureHeaders(answerToken, "", "", "") {
		headers[key] = value
	}
	return headers
}

func signatureHeaders(answerToken string, unionID string, nonce string, timestampMS string) map[string]string {
	token := answerToken
	union := unionID
	if strings.TrimSpace(union) == "" {
		union = randomToken(10)
	}
	nonceValue := nonce
	if strings.TrimSpace(nonceValue) == "" {
		nonceValue = randomToken(16)
	}
	timestamp := timestampMS
	if strings.TrimSpace(timestamp) == "" {
		timestamp = strconv.FormatInt(time.Now().UnixMilli(), 10)
	}
	inner := sha1Upper(token + nonceValue + timestamp + union + cipher)
	signature := sha1Upper(token + nonceValue + timestamp + inner + union + cipher)
	return map[string]string{
		"unionId":   union,
		"nonce":     nonceValue,
		"timestamp": timestamp,
		"signature": signature,
	}
}

func sha1Upper(value string) string {
	sum := sha1.Sum([]byte(value))
	return strings.ToUpper(fmt.Sprintf("%x", sum))
}

func randomToken(length int) string {
	if length <= 0 {
		length = 1
	}
	result := make([]byte, length)
	for i := range result {
		result[i] = randomChars[rand.Intn(len(randomChars))]
	}
	return string(result)
}
