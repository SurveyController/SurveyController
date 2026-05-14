"""问卷星 starttime 提交时长处理。"""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

from software.core.modes.duration_control import (
    has_configured_answer_duration,
    sample_answer_duration_seconds,
    wait_answer_duration_seconds,
)


async def try_apply_submit_starttime(
    driver: Any,
    target_seconds: float,
) -> bool:
    """把问卷星隐藏字段 starttime 改写成目标总作答时长。"""

    normalized_target = max(0.0, float(target_seconds or 0.0))
    if normalized_target <= 0:
        return False
    script = r"""
    const targetSeconds = Math.max(0, Number(arguments[0] || 0));
    if (!targetSeconds) {
        return { ok: false, reason: 'invalid-target' };
    }
    const input = document.getElementById('starttime');
    if (!input) {
        return { ok: false, reason: 'missing-input' };
    }
    const fakeStart = new Date(Date.now() - Math.round(targetSeconds * 1000));
    if (Number.isNaN(fakeStart.getTime())) {
        return { ok: false, reason: 'invalid-date' };
    }
    const pad2 = (value) => String(value).padStart(2, '0');
    const formatted =
        fakeStart.getFullYear() +
        '/' +
        (fakeStart.getMonth() + 1) +
        '/' +
        fakeStart.getDate() +
        ' ' +
        fakeStart.getHours() +
        ':' +
        pad2(fakeStart.getMinutes()) +
        ':' +
        pad2(fakeStart.getSeconds());
    input.value = formatted;
    input.setAttribute('value', formatted);
    try {
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    } catch (error) {}
    try {
        if (typeof starttime !== 'undefined') {
            starttime = fakeStart;
        }
    } catch (error) {}
    try {
        window.starttime = fakeStart;
    } catch (error) {}
    return { ok: true, value: formatted };
    """
    try:
        result = await driver.execute_script(script, normalized_target)
    except Exception as exc:
        logging.warning("问卷星 starttime 改写失败：%s", exc)
        return False
    if isinstance(result, dict):
        if bool(result.get("ok")):
            logging.info(
                "问卷星 starttime 已改写为目标总时长 %.1f 秒，starttime=%s",
                normalized_target,
                result.get("value") or "",
            )
            return True
        logging.warning(
            "问卷星 starttime 改写未生效：reason=%s target=%.1f",
            result.get("reason") or "unknown",
            normalized_target,
        )
        return False
    if bool(result):
        logging.info("问卷星 starttime 已改写为目标总时长 %.1f 秒", normalized_target)
        return True
    logging.warning("问卷星 starttime 改写未生效：target=%.1f", normalized_target)
    return False


async def prepare_answer_duration_before_submit(
    driver: Any,
    stop_signal: Optional[Any] = None,
    answer_duration_range_seconds: Tuple[int, int] = (0, 0),
) -> bool:
    """问卷星提交前优先改写 starttime，失败时回退真实等待。"""

    if not has_configured_answer_duration(answer_duration_range_seconds):
        return False
    target_seconds = sample_answer_duration_seconds(answer_duration_range_seconds)
    if target_seconds <= 0:
        return False
    if await try_apply_submit_starttime(driver, target_seconds):
        return False
    logging.warning(
        "问卷星 starttime 改写失败，回退为真实等待 %.1f 秒。",
        target_seconds,
    )
    return await wait_answer_duration_seconds(stop_signal, target_seconds)


__all__ = [
    "prepare_answer_duration_before_submit",
    "try_apply_submit_starttime",
]
