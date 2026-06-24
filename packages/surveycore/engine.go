package surveycore

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"surveycontroller/surveycore/internal/model"
)

func RunExecution(ctx context.Context, cfg *RuntimeConfig, submit SubmitFunc, handler EventHandler, options ExecutionOptions) (*RunResult, error) {
	if cfg == nil {
		return nil, fmt.Errorf("%w: 配置为空", ErrInvalidConfig)
	}
	if submit == nil {
		return nil, fmt.Errorf("%w: 提交器为空", ErrInvalidConfig)
	}
	target := options.Target
	if target <= 0 {
		target = cfg.Target
	}
	if target <= 0 {
		target = 1
	}
	threads := options.Threads
	if threads <= 0 {
		threads = cfg.Threads
	}
	if threads <= 0 {
		threads = 1
	}
	if threads > target {
		threads = target
	}
	now := options.Now
	if now == nil {
		now = time.Now
	}
	runCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	state := newExecutionState(target, threads, handler, now)
	jobs := make(chan int)
	var wg sync.WaitGroup
	var errMu sync.Mutex
	var firstErr error

	recordErr := func(err error) {
		if err == nil {
			return
		}
		errMu.Lock()
		defer errMu.Unlock()
		if firstErr == nil {
			firstErr = err
		}
	}

	for i := 0; i < threads; i++ {
		workerIndex := i
		workerName := fmt.Sprintf("Worker-%d", i+1)
		wg.Add(1)
		go func() {
			defer wg.Done()
			state.setProgress(workerIndex, workerName, "等待任务", true)
			defer state.setProgress(workerIndex, workerName, "空闲", false)
			hasSubmitted := false
			for job := range jobs {
				if hasSubmitted {
					waitSubmitInterval(runCtx, cfg, state, workerIndex, workerName)
				}
				if runCtx.Err() != nil {
					return
				}
				if err := runOneJob(runCtx, cfg, submit, options, state, workerIndex, workerName, job); err != nil {
					recordErr(err)
					if options.FailStop || !isRetryableRunError(err) {
						cancel()
					}
				} else {
					hasSubmitted = true
				}
				if runCtx.Err() != nil {
					return
				}
			}
		}()
	}

feedLoop:
	for i := 0; i < target; i++ {
		select {
		case <-runCtx.Done():
			break feedLoop
		case jobs <- i:
		}
	}
	close(jobs)
	wg.Wait()

	result := state.result()
	if ctx.Err() != nil && firstErr == nil {
		firstErr = ctx.Err()
	}
	result.Stopped = errors.Is(firstErr, context.Canceled) || errors.Is(firstErr, context.DeadlineExceeded)
	if firstErr != nil {
		return result, firstErr
	}
	return result, nil
}

func runOneJob(ctx context.Context, cfg *RuntimeConfig, submit SubmitFunc, options ExecutionOptions, state *executionState, workerIndex int, workerName string, jobIndex int) error {
	attempts := options.MaxRetries + 1
	if attempts <= 0 {
		attempts = 1
	}
	for attempt := 1; attempt <= attempts; attempt++ {
		if err := ctx.Err(); err != nil {
			state.setProgress(workerIndex, workerName, "已停止", false)
			return err
		}
		owner := fmt.Sprintf("%s-%d-%d", workerName, jobIndex+1, attempt)
		lease, leased, leaseErr := acquireExecutionLease(ctx, cfg, options, state, workerIndex, workerName, owner)
		if leaseErr != nil {
			if shouldRetry(leaseErr, attempt, attempts) {
				state.emit(workerName, "代理不可用，准备重试", false, true)
				sleepRetry(ctx, options.RetryDelay)
				continue
			}
			state.addFail(workerIndex, workerName, "代理不可用")
			return leaseErr
		}

		local := cloneRuntimeConfig(cfg)
		local.Target = 1
		if leased {
			local.ActiveProxyAddress = lease.Address
		}
		local.AnswerRuntimeOwner = owner
		resetPendingAnswerRuntime(&local)
		if options.ConfigureRun != nil {
			if err := options.ConfigureRun(ctx, jobIndex, attempt, &local); err != nil {
				releaseExecutionLease(options, owner, lease, leased, err)
				resetPendingAnswerRuntime(&local)
				state.addFail(workerIndex, workerName, "配置失败")
				return err
			}
		}
		state.setProgress(workerIndex, workerName, "提交中", true)
		result, err := submit(ctx, &local, func(event Event) {
			state.forward(workerIndex, workerName, event)
		})
		releaseExecutionLease(options, owner, lease, leased, err)
		finalizeAnswerRuntime(&local, err == nil)

		if err == nil {
			state.addSuccess(workerIndex, workerName, "提交成功")
			return nil
		}
		statusText := statusFromRunResult(result, err)
		if shouldRetry(err, attempt, attempts) {
			state.setProgress(workerIndex, workerName, "准备重试", true)
			state.emit(workerName, "提交失败，准备重试", false, true)
			sleepRetry(ctx, options.RetryDelay)
			continue
		}
		state.addFail(workerIndex, workerName, statusText)
		return err
	}
	return ErrRunFailed
}

func waitSubmitInterval(ctx context.Context, cfg *RuntimeConfig, state *executionState, workerIndex int, workerName string) {
	if cfg == nil {
		return
	}
	seconds := model.SampleSubmitIntervalSeconds(cfg.SubmitInterval)
	if seconds <= 0 {
		return
	}
	state.setProgress(workerIndex, workerName, "等待提交间隔", true)
	sleepRetry(ctx, time.Duration(seconds)*time.Second)
}

func acquireExecutionLease(ctx context.Context, cfg *RuntimeConfig, options ExecutionOptions, state *executionState, workerIndex int, workerName string, owner string) (ExecutionLease, bool, error) {
	if !cfg.RandomIPEnabled || options.LeaseManager == nil {
		return ExecutionLease{}, false, nil
	}
	state.setProgress(workerIndex, workerName, "申请代理", true)
	lease, err := options.LeaseManager.Acquire(ctx, owner)
	if err != nil {
		return ExecutionLease{}, false, err
	}
	if lease.Address != "" {
		state.emit(workerName, "代理已分配", false, false)
	}
	return lease, true, nil
}

func releaseExecutionLease(options ExecutionOptions, owner string, lease ExecutionLease, leased bool, submitErr error) {
	if !leased || options.LeaseManager == nil {
		return
	}
	if submitErr == nil {
		options.LeaseManager.MarkSuccess(lease.Address)
	} else if options.CooldownOnError > 0 {
		options.LeaseManager.MarkCooldown(lease.Address, options.CooldownOnError)
	}
	options.LeaseManager.Release(owner)
}

func shouldRetry(err error, attempt int, attempts int) bool {
	return attempt < attempts && isRetryableRunError(err)
}

func isRetryableRunError(err error) bool {
	return ClassifyRunError(err) == ErrorKindRun
}

func sleepRetry(ctx context.Context, delay time.Duration) {
	if delay <= 0 {
		return
	}
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
	case <-timer.C:
	}
}

func statusFromRunResult(result *RunResult, err error) string {
	if result != nil && len(result.ThreadProgress) > 0 && result.ThreadProgress[0].StatusText != "" {
		return result.ThreadProgress[0].StatusText
	}
	switch ClassifyRunError(err) {
	case ErrorKindUnsupported:
		return "unsupported"
	case ErrorKindCanceled:
		return "stopped"
	case ErrorKindParse:
		return "parse_failed"
	case ErrorKindConfig:
		return "config_failed"
	default:
		return "failed"
	}
}

type executionState struct {
	mu       sync.Mutex
	target   int
	success  int
	fail     int
	progress []ThreadProgress
	handler  EventHandler
	now      func() time.Time
}

func newExecutionState(target int, threads int, handler EventHandler, now func() time.Time) *executionState {
	progress := make([]ThreadProgress, threads)
	for i := range progress {
		progress[i] = ThreadProgress{
			ThreadName:  fmt.Sprintf("Worker-%d", i+1),
			ThreadIndex: i,
			StepTotal:   target,
			StatusText:  "等待任务",
			LastUpdate:  now(),
		}
	}
	return &executionState{target: target, progress: progress, handler: handler, now: now}
}

func (s *executionState) setProgress(index int, worker string, status string, running bool) {
	s.mu.Lock()
	if index >= 0 && index < len(s.progress) {
		s.progress[index].ThreadName = worker
		s.progress[index].ThreadIndex = index
		s.progress[index].StepTotal = s.target
		s.progress[index].StatusText = status
		s.progress[index].Running = running
		s.progress[index].LastUpdate = s.now()
	}
	s.mu.Unlock()
}

func (s *executionState) forward(index int, worker string, event Event) {
	if event.Time.IsZero() {
		event.Time = s.now()
	}
	event.Worker = worker
	s.mu.Lock()
	if index >= 0 && index < len(s.progress) {
		if event.Message != "" {
			s.progress[index].StatusText = event.Message
		}
		s.progress[index].Running = true
		s.progress[index].LastUpdate = event.Time
	}
	current := s.success + s.fail
	s.mu.Unlock()
	event.Current = current
	event.Total = s.target
	if s.handler != nil {
		s.handler(event)
	}
}

func (s *executionState) addSuccess(index int, worker string, status string) {
	s.mu.Lock()
	s.success++
	current := s.success + s.fail
	now := s.now()
	if index >= 0 && index < len(s.progress) {
		s.progress[index].SuccessCount++
		s.progress[index].StepCurrent = current
		s.progress[index].StepTotal = s.target
		s.progress[index].StatusText = status
		s.progress[index].Running = true
		s.progress[index].LastUpdate = now
	}
	s.mu.Unlock()
	s.callHandler(Event{Worker: worker, Message: status, Success: true, Current: current, Total: s.target, Time: now})
}

func (s *executionState) addFail(index int, worker string, status string) {
	s.mu.Lock()
	s.fail++
	current := s.success + s.fail
	now := s.now()
	if index >= 0 && index < len(s.progress) {
		s.progress[index].FailCount++
		s.progress[index].StepCurrent = current
		s.progress[index].StepTotal = s.target
		s.progress[index].StatusText = status
		s.progress[index].Running = true
		s.progress[index].LastUpdate = now
	}
	s.mu.Unlock()
	s.callHandler(Event{Worker: worker, Message: status, Fail: true, Current: current, Total: s.target, Time: now})
}

func (s *executionState) emit(worker string, message string, success bool, fail bool) {
	s.mu.Lock()
	current := s.success + s.fail
	now := s.now()
	s.mu.Unlock()
	s.callHandler(Event{Worker: worker, Message: message, Success: success, Fail: fail, Current: current, Total: s.target, Time: now})
}

func (s *executionState) callHandler(event Event) {
	if s.handler != nil {
		s.handler(event)
	}
}

func (s *executionState) result() *RunResult {
	s.mu.Lock()
	defer s.mu.Unlock()
	progress := make([]ThreadProgress, len(s.progress))
	copy(progress, s.progress)
	return &RunResult{
		Success:        s.success,
		Fail:           s.fail,
		ThreadProgress: progress,
	}
}
