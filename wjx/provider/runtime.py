"""问卷星运行时能力（provider 入口）。"""

from __future__ import annotations

import threading
from typing import Any, Optional

from software.core.task import TaskContext
from software.network.browser import BrowserDriver
from wjx.provider.detection import detect as _wjx_detect

_WJX_RUNTIME_GUARD = threading.local()


def _dispatch_wjx_brush(
    driver: BrowserDriver,
    ctx: TaskContext,
    *,
    stop_signal: Optional[threading.Event],
    thread_name: str,
    psycho_plan: Optional[Any],
) -> bool:
    # 延迟导入：避免 registry / runtime / answering 在模块加载阶段互相循环导入。
    from software.core.engine.answering import brush as _brush

    return _brush(
        driver,
        ctx,
        stop_signal=stop_signal,
        thread_name=thread_name,
        psycho_plan=psycho_plan,
        provider_dispatched=True,
        detect_fn=_wjx_detect,
    )


def brush_wjx(
    driver: BrowserDriver,
    ctx: TaskContext,
    *,
    stop_signal: Optional[threading.Event],
    thread_name: str,
    psycho_plan: Optional[Any],
) -> bool:
    """问卷星 provider 运行时入口。"""
    if bool(getattr(_WJX_RUNTIME_GUARD, "active", False)):
        raise RuntimeError(
            "检测到 WJX runtime 与 answering 递归调用，已中止以避免死循环。"
        )
    _WJX_RUNTIME_GUARD.active = True
    try:
        return _dispatch_wjx_brush(
            driver,
            ctx,
            stop_signal=stop_signal,
            thread_name=thread_name,
            psycho_plan=psycho_plan,
        )
    finally:
        _WJX_RUNTIME_GUARD.active = False


def fill_survey(
    driver: BrowserDriver,
    ctx: TaskContext,
    *,
    stop_signal: Optional[threading.Event],
    thread_name: str,
    psycho_plan: Optional[Any],
) -> bool:
    """provider 统一入口别名。"""
    return brush_wjx(
        driver,
        ctx,
        stop_signal=stop_signal,
        thread_name=thread_name,
        psycho_plan=psycho_plan,
    )


__all__ = [
    "brush_wjx",
    "fill_survey",
]


