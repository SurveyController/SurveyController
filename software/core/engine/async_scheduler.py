"""Async scheduler for fill attempts."""

from __future__ import annotations

import asyncio
from collections import deque
import heapq
import itertools
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass(order=True)
class _ScheduledToken:
    ready_at: float
    order: int
    token_id: int = field(compare=False)


class AsyncScheduler:
    """Bounded async attempt scheduler with delayed requeue."""

    def __init__(self, *, concurrency: int) -> None:
        self._concurrency = max(1, int(concurrency or 1))
        self._ready: deque[int] = deque()
        self._delayed: list[_ScheduledToken] = []
        self._order = itertools.count()
        self._condition = asyncio.Condition()
        self._closed = False
        self._waker_task: Optional[asyncio.Task[None]] = None
        for token_id in range(self._concurrency):
            self._ready.append(token_id)

    async def start(self) -> None:
        if self._waker_task is None:
            self._waker_task = asyncio.create_task(self._wake_delayed_tokens(), name="AsyncSchedulerWake")

    async def acquire(self) -> Optional[int]:
        await self.start()
        async with self._condition:
            while True:
                if self._closed:
                    return None
                if self._ready:
                    return self._ready.popleft()
                await self._condition.wait()

    async def release(self, token_id: int, *, requeue: bool, delay_seconds: float = 0.0) -> None:
        if not requeue:
            return
        delay = max(0.0, float(delay_seconds or 0.0))
        async with self._condition:
            if self._closed:
                return
            if delay <= 0:
                self._ready.append(int(token_id))
                self._condition.notify_all()
                return
            heapq.heappush(
                self._delayed,
                _ScheduledToken(time.monotonic() + delay, next(self._order), int(token_id)),
            )
            self._condition.notify_all()

    async def _wake_delayed_tokens(self) -> None:
        while True:
            async with self._condition:
                if self._closed:
                    return
                now = time.monotonic()
                moved = False
                while self._delayed and self._delayed[0].ready_at <= now:
                    token = heapq.heappop(self._delayed)
                    self._ready.append(token.token_id)
                    moved = True
                if moved:
                    self._condition.notify_all()
                    continue
                sleep_for = 0.1
                if self._delayed:
                    sleep_for = min(0.1, max(0.0, self._delayed[0].ready_at - now))
            try:
                await asyncio.sleep(sleep_for)
            except asyncio.CancelledError:
                break

    async def close(self) -> None:
        self._closed = True
        if self._waker_task is not None:
            self._waker_task.cancel()
            await asyncio.gather(self._waker_task, return_exceptions=True)
            self._waker_task = None
        async with self._condition:
            self._condition.notify_all()


__all__ = ["AsyncScheduler"]
