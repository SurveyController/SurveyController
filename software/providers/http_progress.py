from __future__ import annotations

import asyncio
import logging
from typing import Any


HTTP_SUBMIT_STEPS: tuple[str, ...] = (
    "准备请求",
    "生成答案",
    "提交问卷",
    "校验结果",
)
HTTP_SUBMIT_STEP_TOTAL = len(HTTP_SUBMIT_STEPS)
HTTP_SUBMIT_STEP_MIN_VISIBLE_SECONDS = 0.008


async def update_http_submit_step(
    state: Any,
    thread_name: str,
    step_label: str,
    *,
    min_visible_seconds: float = HTTP_SUBMIT_STEP_MIN_VISIBLE_SECONDS,
) -> None:
    

    label = str(step_label or "").strip()
    try:
        current = HTTP_SUBMIT_STEPS.index(label) + 1
    except ValueError:
        current = 0
    try:
        state.update_thread_step(
            thread_name,
            current,
            HTTP_SUBMIT_STEP_TOTAL,
            status_text=label,
            running=True,
        )
    except Exception:
        logging.info("更新 HTTP 提交步骤失败：%s", label, exc_info=True)
    delay = max(0.0, float(min_visible_seconds or 0.0))
    if delay > 0:
        await asyncio.sleep(delay)


__all__ = [
    "HTTP_SUBMIT_STEPS",
    "HTTP_SUBMIT_STEP_MIN_VISIBLE_SECONDS",
    "HTTP_SUBMIT_STEP_TOTAL",
    "update_http_submit_step",
]
