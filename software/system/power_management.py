"""运行期间的系统电源管理。"""

from __future__ import annotations

import ctypes
import logging
import sys


_ES_SYSTEM_REQUIRED = 0x00000001
_ES_CONTINUOUS = 0x80000000


class SystemSleepBlocker:
    """在任务执行期间阻止系统自动休眠。"""

    def __init__(self) -> None:
        self._active = False

    @property
    def active(self) -> bool:
        return bool(self._active)

    def acquire(self) -> bool:
        if self._active:
            return True
        if sys.platform != "win32":
            return False
        try:
            result = ctypes.windll.kernel32.SetThreadExecutionState(  # type: ignore[attr-defined]
                _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
            )
        except Exception:
            logging.warning("申请阻止系统自动休眠失败", exc_info=True)
            return False
        if not result:
            logging.warning("申请阻止系统自动休眠失败：SetThreadExecutionState 返回 0")
            return False
        self._active = True
        logging.info("已启用执行期间阻止系统自动休眠")
        return True

    def release(self) -> bool:
        if not self._active:
            return True
        if sys.platform != "win32":
            self._active = False
            return True
        try:
            result = ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)  # type: ignore[attr-defined]
        except Exception:
            logging.warning("恢复系统自动休眠状态失败", exc_info=True)
            return False
        if not result:
            logging.warning("恢复系统自动休眠状态失败：SetThreadExecutionState 返回 0")
            return False
        self._active = False
        logging.info("已恢复系统自动休眠状态")
        return True


__all__ = ["SystemSleepBlocker"]
