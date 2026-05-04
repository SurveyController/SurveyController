from __future__ import annotations

import asyncio

from software.core.engine.async_engine import AsyncEngineClient


def test_submit_ui_task_runs_on_background_loop() -> None:
    client = AsyncEngineClient()
    try:
        future = client.submit_ui_task("unit-test", lambda: _return_value())
        assert future.result(timeout=2.0) == "ok"
    finally:
        client.shutdown(timeout=2.0)


async def _return_value() -> str:
    await asyncio.sleep(0)
    return "ok"
