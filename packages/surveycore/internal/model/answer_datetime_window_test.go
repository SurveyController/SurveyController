package model

import (
	"testing"
	"time"
)

func TestNormalizeAnswerDatetimeWindow(t *testing.T) {
	window := NormalizeAnswerDatetimeWindow([2]string{
		" 2024-03-10 09:00:00 ",
		"bad",
	})
	if window != [2]string{"2024-03-10 09:00:00", ""} {
		t.Fatalf("window = %#v", window)
	}
}

func TestAnswerDatetimeWindowToEpochMS(t *testing.T) {
	window := [2]string{"2024-03-10 09:00:00", "2024-03-10 10:00:00"}
	startMS, endMS := AnswerDatetimeWindowToEpochMS(window)
	start, _ := time.ParseInLocation(AnswerDatetimeWindowLayout, window[0], time.Local)
	end, _ := time.ParseInLocation(AnswerDatetimeWindowLayout, window[1], time.Local)
	if startMS != start.UnixMilli() || endMS != end.UnixMilli() {
		t.Fatalf("startMS=%d endMS=%d", startMS, endMS)
	}
}
