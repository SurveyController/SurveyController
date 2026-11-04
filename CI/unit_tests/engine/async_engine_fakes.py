from __future__ import annotations

import asyncio
from types import SimpleNamespace

from software.core.engine.async_engine import AsyncRuntimeEngine


class FakeLoop:
    def __init__(self) -> None:
        self.stopped = False
        self.closed = False
        self.threadsafe_calls: list[tuple[object, tuple[object, ...]]] = []
        self.run_forever_calls = 0
        self.run_until_complete_calls: list[object] = []
        self.shutdown_asyncgens_calls = 0

    def run_forever(self) -> None:
        self.run_forever_calls += 1

    def run_until_complete(self, awaitable) -> None:
        self.run_until_complete_calls.append(awaitable)
        if asyncio.iscoroutine(awaitable):
            asyncio.run(awaitable)

    async def shutdown_asyncgens(self) -> None:
        self.shutdown_asyncgens_calls += 1

    def close(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed

    def call_soon_threadsafe(self, callback, *args) -> None:
        self.threadsafe_calls.append((callback, args))
        callback(*args)

    def stop(self) -> None:
        self.stopped = True


class FakeThread:
    created: list["FakeThread"] = []

    def __init__(self, *, target, daemon: bool, name: str) -> None:
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False
        self.join_calls: list[float | None] = []
        FakeThread.created.append(self)

    def start(self) -> None:
        self.started = True
        self.target()

    def is_alive(self) -> bool:
        return self.started

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)


class DoneFuture:
    def __init__(
        self, *, done: bool = True, result_value=None, result_error: Exception | None = None
    ) -> None:
        self._done = done
        self._result_value = result_value
        self._result_error = result_error
        self.result_calls: list[float | None] = []

    def done(self) -> bool:
        return self._done

    def result(self, timeout: float | None = None):
        self.result_calls.append(timeout)
        if self._result_error is not None:
            raise self._result_error
        return self._result_value


def build_engine() -> AsyncRuntimeEngine:
    return AsyncRuntimeEngine(status_bus=SimpleNamespace(emit=lambda _event: None))
