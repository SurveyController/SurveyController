from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any


class TaskRegistry:
    """Owns detached asyncio tasks on one event loop."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()
        self._accepting = True

    def create_task(
        self,
        coroutine: Coroutine[Any, Any, Any],
        *,
        name: str,
    ) -> asyncio.Task[Any]:
        if not self._accepting:
            coroutine.close()
            raise RuntimeError("任务注册表正在关闭，不接受新任务")
        try:
            task = asyncio.create_task(coroutine, name=name)
        except Exception:
            coroutine.close()
            raise
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            logging.warning("后台任务失败：%s：%s", task.get_name(), exception)

    async def drain(self, timeout: float = 5.0) -> int:
        self._accepting = False
        tasks = set(self._tasks)
        if not tasks:
            return 0
        _, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout))
        if not pending:
            return 0
        for task in pending:
            task.cancel()
        _, still_pending = await asyncio.wait(pending, timeout=0.5)
        if still_pending:
            names = ", ".join(sorted(task.get_name() for task in still_pending))
            logging.warning(
                "关闭超时后仍有 %d 个后台任务未退出：%s",
                len(still_pending),
                names,
            )
        cancelled = len(pending) - len(still_pending)
        if cancelled:
            logging.warning("关闭时已取消 %d 个未完成后台任务", cancelled)
        return len(still_pending)


__all__ = ["TaskRegistry"]
