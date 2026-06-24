package model

import (
	"strings"
	"time"
)

const AnswerDatetimeWindowLayout = "2006-01-02 15:04:05"

func ParseAnswerDatetimeString(value string) (time.Time, bool) {
	text := strings.TrimSpace(value)
	if text == "" {
		return time.Time{}, false
	}
	parsed, err := time.ParseInLocation(AnswerDatetimeWindowLayout, text, time.Local)
	if err != nil {
		return time.Time{}, false
	}
	return parsed, true
}

func NormalizeAnswerDatetimeWindow(value [2]string) [2]string {
	var result [2]string
	if start, ok := ParseAnswerDatetimeString(value[0]); ok {
		result[0] = start.Format(AnswerDatetimeWindowLayout)
	}
	if end, ok := ParseAnswerDatetimeString(value[1]); ok {
		result[1] = end.Format(AnswerDatetimeWindowLayout)
	}
	return result
}

func HasConfiguredAnswerDatetimeWindow(value [2]string) bool {
	normalized := NormalizeAnswerDatetimeWindow(value)
	return normalized[0] != "" && normalized[1] != ""
}

func AnswerDatetimeWindowToEpochMS(value [2]string) (int64, int64) {
	normalized := NormalizeAnswerDatetimeWindow(value)
	start, startOK := ParseAnswerDatetimeString(normalized[0])
	end, endOK := ParseAnswerDatetimeString(normalized[1])
	if !startOK || !endOK {
		return 0, 0
	}
	return start.UnixMilli(), end.UnixMilli()
}
