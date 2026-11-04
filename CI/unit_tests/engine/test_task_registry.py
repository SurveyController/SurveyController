from __future__ import annotations

import asyncio

import pytest

from software.core.engine.task_registry import TaskRegistry


@pytest.mark.asyncio
async def test_registry_drains_owned_tasks_before_returning() -> None:
    registry = TaskRegistry()
    completed = asyncio.Event()

    async def report() -> None:
        await asyncio.sleep(0)
        completed.set()

    task = registry.create_task(report(), name="report")
    dropped = await registry.drain(timeout=1.0)

    assert dropped == 0
    assert completed.is_set()
    assert task.done()


@pytest.mark.asyncio
async def test_registry_cancels_tasks_that_exceed_drain_timeout() -> None:
    registry = TaskRegistry()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = registry.create_task(blocked(), name="blocked")
    await started.wait()
    dropped = await registry.drain(timeout=0)

    assert dropped == 1
    assert cancelled.is_set()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_registry_closes_coroutine_when_rejecting_after_drain() -> None:
    registry = TaskRegistry()
    await registry.drain()

    async def late_task() -> None:
        return None

    coroutine = late_task()
    with pytest.raises(RuntimeError, match="正在关闭"):
        registry.create_task(coroutine, name="late")

    assert coroutine.cr_frame is None


@pytest.mark.asyncio
async def test_registry_returns_when_task_does_not_finish_cancellation() -> None:
    registry = TaskRegistry()
    release = asyncio.Event()

    async def suppress_cancellation() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    task = registry.create_task(suppress_cancellation(), name="stuck-task")
    await asyncio.sleep(0)

    dropped = await registry.drain(timeout=0)

    assert dropped == 1
    assert not task.done()
    release.set()
    await task
