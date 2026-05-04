"""线程/协程共用的停止信号协议。"""

from __future__ import annotations

from typing import Optional, Protocol


class StopSignalLike(Protocol):
    def is_set(self) -> bool: ...

    def set(self) -> None: ...

    def wait(self, timeout: Optional[float] = None) -> bool: ...


__all__ = ["StopSignalLike"]
