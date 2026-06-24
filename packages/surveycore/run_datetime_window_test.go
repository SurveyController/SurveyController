package surveycore

import (
	"errors"
	"testing"
)

func TestPrepareAnswerDatetimeWindowRejectsIncompleteCredamoWindow(t *testing.T) {
	cfg := &RuntimeConfig{
		AnswerDuration:       [2]int{30, 60},
		AnswerDatetimeWindow: [2]string{"2024-03-10 09:00:00", ""},
	}
	err := prepareAnswerDatetimeWindowExecution(cfg, ProviderCredamo)
	if !errors.Is(err, ErrPrepareConfigFailed) {
		t.Fatalf("err = %v", err)
	}
}

func TestPrepareAnswerDatetimeWindowRejectsNarrowCredamoWindow(t *testing.T) {
	cfg := &RuntimeConfig{
		AnswerDuration:       [2]int{30, 60},
		AnswerDatetimeWindow: [2]string{"2024-03-10 09:00:00", "2024-03-10 09:00:10"},
	}
	err := prepareAnswerDatetimeWindowExecution(cfg, ProviderCredamo)
	if !errors.Is(err, ErrPrepareConfigFailed) {
		t.Fatalf("err = %v", err)
	}
}

func TestPrepareAnswerDatetimeWindowIgnoresUnsupportedProvider(t *testing.T) {
	cfg := &RuntimeConfig{
		AnswerDuration:       [2]int{30, 60},
		AnswerDatetimeWindow: [2]string{"2024-03-10 09:00:00", ""},
	}
	if err := prepareAnswerDatetimeWindowExecution(cfg, ProviderWJX); err != nil {
		t.Fatalf("err = %v", err)
	}
}
