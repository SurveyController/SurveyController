from __future__ import annotations

import asyncio

from software.core.engine.async_scheduler import AsyncScheduler


async def test_scheduler_enforces_bounded_tokens() -> None:
    scheduler = AsyncScheduler(concurrency=2)
    try:
        first = await scheduler.acquire()
        second = await scheduler.acquire()
        assert first is not None
        assert second is not None

        waiter = asyncio.create_task(scheduler.acquire())
        await asyncio.sleep(0.05)
        assert not waiter.done()

        await scheduler.release(first or 0, requeue=True)
        assert await asyncio.wait_for(waiter, timeout=1.0) == first
    finally:
        await scheduler.close()


async def test_scheduler_delays_requeued_token() -> None:
    scheduler = AsyncScheduler(concurrency=1)
    try:
        token = await scheduler.acquire()
        assert token is not None
        await scheduler.release(token or 0, requeue=True, delay_seconds=0.05)
        delayed = asyncio.create_task(scheduler.acquire())
        await asyncio.sleep(0.01)
        assert not delayed.done()
        assert await asyncio.wait_for(delayed, timeout=1.0) == token
    finally:
        await scheduler.close()
