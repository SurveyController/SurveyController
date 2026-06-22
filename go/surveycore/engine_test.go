package surveycore

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"testing"
	"time"
)

func TestRunExecutionRunsTargetWithConcurrency(t *testing.T) {
	var mu sync.Mutex
	active := 0
	maxActive := 0
	result, err := RunExecution(context.Background(), &RuntimeConfig{URL: "https://example.test", Target: 5, Threads: 3}, func(ctx context.Context, cfg *RuntimeConfig, _ EventHandler) (*RunResult, error) {
		if cfg.Target != 1 {
			t.Fatalf("cfg.Target = %d, want 1", cfg.Target)
		}
		mu.Lock()
		active++
		if active > maxActive {
			maxActive = active
		}
		mu.Unlock()
		time.Sleep(10 * time.Millisecond)
		mu.Lock()
		active--
		mu.Unlock()
		return &RunResult{Success: 1}, nil
	}, nil, ExecutionOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if result.Success != 5 || result.Fail != 0 || len(result.ThreadProgress) != 3 {
		t.Fatalf("result = %#v", result)
	}
	if maxActive < 2 || maxActive > 3 {
		t.Fatalf("maxActive = %d", maxActive)
	}
}

func TestRunExecutionRetriesRunError(t *testing.T) {
	var attempts int
	var events []Event
	result, err := RunExecution(context.Background(), &RuntimeConfig{URL: "https://example.test", Target: 1, Threads: 1}, func(_ context.Context, _ *RuntimeConfig, _ EventHandler) (*RunResult, error) {
		attempts++
		if attempts == 1 {
			return &RunResult{Fail: 1}, errors.New("temporary network failure")
		}
		return &RunResult{Success: 1}, nil
	}, func(event Event) {
		events = append(events, event)
	}, ExecutionOptions{MaxRetries: 1})
	if err != nil {
		t.Fatal(err)
	}
	if attempts != 2 || result.Success != 1 || result.Fail != 0 {
		t.Fatalf("attempts=%d result=%#v", attempts, result)
	}
	if len(events) == 0 {
		t.Fatal("expected retry events")
	}
}

func TestRunExecutionCancelsAndStopsWorkers(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	var started sync.WaitGroup
	started.Add(1)
	result, err := RunExecution(ctx, &RuntimeConfig{URL: "https://example.test", Target: 3, Threads: 1}, func(ctx context.Context, _ *RuntimeConfig, _ EventHandler) (*RunResult, error) {
		started.Done()
		cancel()
		<-ctx.Done()
		return &RunResult{}, ctx.Err()
	}, nil, ExecutionOptions{})
	started.Wait()
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("err = %v", err)
	}
	if result == nil || !result.Stopped {
		t.Fatalf("result = %#v", result)
	}
}

func TestRunExecutionLeaseLifecycle(t *testing.T) {
	leases := &fakeLeaseManager{}
	result, err := RunExecution(context.Background(), &RuntimeConfig{
		URL:             "https://example.test",
		Target:          2,
		Threads:         1,
		RandomIPEnabled: true,
	}, func(_ context.Context, _ *RuntimeConfig, _ EventHandler) (*RunResult, error) {
		return &RunResult{Success: 1}, nil
	}, nil, ExecutionOptions{LeaseManager: leases})
	if err != nil {
		t.Fatal(err)
	}
	if result.Success != 2 {
		t.Fatalf("result = %#v", result)
	}
	if leases.acquired != 2 || leases.released != 2 || leases.success != 2 {
		t.Fatalf("leases = %#v", leases)
	}
}

func TestRunExecutionClassifiesUnsupportedWithoutRetry(t *testing.T) {
	var attempts int
	result, err := RunExecution(context.Background(), &RuntimeConfig{URL: "https://example.test", Target: 1, Threads: 1}, func(_ context.Context, _ *RuntimeConfig, _ EventHandler) (*RunResult, error) {
		attempts++
		return &RunResult{}, fmt.Errorf("%w: no runner", ErrUnsupportedOperation)
	}, nil, ExecutionOptions{MaxRetries: 3})
	if !errors.Is(err, ErrUnsupportedOperation) {
		t.Fatalf("err = %v", err)
	}
	if attempts != 1 {
		t.Fatalf("attempts = %d", attempts)
	}
	if result == nil || result.Fail != 1 {
		t.Fatalf("result = %#v", result)
	}
}

type fakeLeaseManager struct {
	acquired int
	released int
	success  int
	cooldown int
}

func (m *fakeLeaseManager) Acquire(_ context.Context, _ string) (ExecutionLease, error) {
	m.acquired++
	return ExecutionLease{Address: fmt.Sprintf("http://127.0.0.%d:8000", m.acquired), Source: "fake"}, nil
}

func (m *fakeLeaseManager) Release(_ string) (ExecutionLease, bool) {
	m.released++
	return ExecutionLease{}, true
}

func (m *fakeLeaseManager) MarkSuccess(_ string) bool {
	m.success++
	return true
}

func (m *fakeLeaseManager) MarkCooldown(_ string, _ time.Duration) {
	m.cooldown++
}
