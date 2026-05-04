from __future__ import annotations

import asyncio
import unittest

from software.core.engine.async_scheduler import AsyncScheduler


class AsyncSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_enforces_bounded_tokens(self) -> None:
        scheduler = AsyncScheduler(concurrency=2)
        try:
            first = await scheduler.acquire()
            second = await scheduler.acquire()
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)

            waiter = asyncio.create_task(scheduler.acquire())
            await asyncio.sleep(0.05)
            self.assertFalse(waiter.done())

            await scheduler.release(first or 0, requeue=True)
            self.assertEqual(await asyncio.wait_for(waiter, timeout=1.0), first)
        finally:
            await scheduler.close()

    async def test_scheduler_delays_requeued_token(self) -> None:
        scheduler = AsyncScheduler(concurrency=1)
        try:
            token = await scheduler.acquire()
            self.assertIsNotNone(token)
            await scheduler.release(token or 0, requeue=True, delay_seconds=0.05)
            delayed = asyncio.create_task(scheduler.acquire())
            await asyncio.sleep(0.01)
            self.assertFalse(delayed.done())
            self.assertEqual(await asyncio.wait_for(delayed, timeout=1.0), token)
        finally:
            await scheduler.close()


if __name__ == "__main__":
    unittest.main()
