package surveycore

import (
	"context"
	"os"
	"testing"
	"time"
)

func TestLiveCredamoSubmit(t *testing.T) {
	runLiveSubmit(t, "SC_CREDAMO_LIVE_URL", ProviderCredamo)
}

func TestLiveWJXSubmit(t *testing.T) {
	runLiveSubmit(t, "SC_WJX_LIVE_URL", ProviderWJX)
}

func runLiveSubmit(t *testing.T, urlEnv string, provider string) {
	t.Helper()
	if os.Getenv("SC_LIVE_SUBMIT") != "1" {
		t.Skip("SC_LIVE_SUBMIT is not 1")
	}
	surveyURL := os.Getenv(urlEnv)
	if surveyURL == "" {
		t.Skip(urlEnv + " not set")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	client := New()
	cfg, err := client.DefaultConfig(ctx, surveyURL)
	if err != nil {
		t.Fatal(err)
	}
	cfg.SurveyProvider = provider
	cfg.Target = 1
	cfg.Threads = 1
	result, err := client.Run(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if result == nil || result.Success != 1 {
		t.Fatalf("result = %#v", result)
	}
}
