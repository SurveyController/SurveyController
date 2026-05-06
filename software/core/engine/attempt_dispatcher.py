"""中央调度器：把“下一轮尝试机会”做成共享队列。"""

from __future__ import annotations

import heapq
import threading
import time

from software.core.task import ExecutionConfig, ExecutionState

_STOP_POLL_SECONDS = 0.2


class AttemptDispatcher:
    """维护固定数量的尝试令牌，支持延迟回队与阻塞唤醒。"""

    def __init__(
        self,
        config: ExecutionConfig,
        state: ExecutionState,
        stop_signal: threading.Event,
    ) -> None:
        self.config = config
        self.state = state
        self.stop_signal = stop_signal
        self._condition = threading.Condition()
        self._ready_tokens = max(1, int(config.num_threads or 1))
        self._delayed_ready_heap: list[float] = []
        self._active_attempts = 0
        self._closed = False

    def _flush_due_tokens_locked(self, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else float(now)
        while self._delayed_ready_heap and self._delayed_ready_heap[0] <= current:
            heapq.heappop(self._delayed_ready_heap)
            self._ready_tokens += 1

    def _should_stop_locked(self) -> bool:
        if self._closed or self.stop_signal.is_set():
            return True
        if self.config.target_num <= 0:
            return False
        with self.state.lock:
            return bool(self.state.cur_num >= self.config.target_num)

    def acquire(self) -> bool:
        with self._condition:
            while True:
                now = time.monotonic()
                self._flush_due_tokens_locked(now=now)
                if self._should_stop_locked():
                    return False
                if self._ready_tokens > 0:
                    self._ready_tokens -= 1
                    self._active_attempts += 1
                    return True
                timeout = None
                if self._delayed_ready_heap:
                    timeout = max(0.0, self._delayed_ready_heap[0] - now)
                    timeout = min(timeout, _STOP_POLL_SECONDS)
                else:
                    timeout = _STOP_POLL_SECONDS
                self._condition.wait(timeout=timeout)

    def release(self, *, requeue: bool, delay_seconds: float = 0.0) -> None:
        with self._condition:
            if self._active_attempts > 0:
                self._active_attempts -= 1
            if requeue and not self._closed and not self.stop_signal.is_set():
                delay = max(0.0, float(delay_seconds or 0.0))
                if delay > 0:
                    heapq.heappush(self._delayed_ready_heap, time.monotonic() + delay)
                else:
                    self._ready_tokens += 1
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


__all__ = ["AttemptDispatcher"]
