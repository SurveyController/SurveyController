package model

import "testing"

func TestSelectUserAgentFromRatiosUsesConfiguredDevice(t *testing.T) {
	profile, ok := SelectUserAgentFromRatios(map[string]int{"wechat": 0, "mobile": 0, "pc": 100})
	if !ok {
		t.Fatal("expected profile")
	}
	if profile.Category != "pc" || profile.PresetKey != "pc_web" || profile.UserAgent == "" {
		t.Fatalf("profile = %#v", profile)
	}
}

func TestSelectUserAgentFromRatiosFallsBackOnInvalidRatios(t *testing.T) {
	profile, ok := SelectUserAgentFromRatios(map[string]int{"wechat": 1, "mobile": 1, "pc": 1})
	if !ok {
		t.Fatal("expected fallback profile")
	}
	if profile.UserAgent == "" {
		t.Fatalf("profile = %#v", profile)
	}
}

func TestRuntimeUserAgentDisabledReturnsEmpty(t *testing.T) {
	ua := RuntimeUserAgent(&RuntimeConfig{
		RandomUAEnabled: false,
		RandomUARatios:  map[string]int{"wechat": 0, "mobile": 0, "pc": 100},
	})
	if ua != "" {
		t.Fatalf("ua = %q", ua)
	}
}

func TestSampleAnswerDurationSecondsStaysInRange(t *testing.T) {
	for i := 0; i < 100; i++ {
		value := SampleAnswerDurationSeconds([2]int{30, 90}, 60)
		if value < 30 || value > 90 {
			t.Fatalf("value = %d", value)
		}
	}
}

func TestSampleSubmitIntervalSecondsStaysInRange(t *testing.T) {
	for i := 0; i < 100; i++ {
		value := SampleSubmitIntervalSeconds([2]int{2, 5})
		if value < 2 || value > 5 {
			t.Fatalf("value = %d", value)
		}
	}
}
