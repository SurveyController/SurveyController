"""浏览器 owner 池的纯配置定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

DEFAULT_HEADED_CONTEXTS_PER_BROWSER = 4
DEFAULT_HEADLESS_CONTEXTS_PER_BROWSER = 8


@dataclass(frozen=True)
class BrowserPoolConfig:
    logical_concurrency: int
    contexts_per_owner: int
    owner_count: int
    headless: bool = False

    @classmethod
    def from_concurrency(
        cls,
        logical_concurrency: int,
        *,
        headless: bool,
        contexts_per_owner: Optional[int] = None,
    ) -> "BrowserPoolConfig":
        concurrency = max(1, int(logical_concurrency or 1))
        default_capacity = (
            DEFAULT_HEADLESS_CONTEXTS_PER_BROWSER
            if bool(headless)
            else DEFAULT_HEADED_CONTEXTS_PER_BROWSER
        )
        normalized_capacity = max(1, int(contexts_per_owner or default_capacity))
        owner_count = max(1, (concurrency + normalized_capacity - 1) // normalized_capacity)
        return cls(
            logical_concurrency=concurrency,
            contexts_per_owner=normalized_capacity,
            owner_count=owner_count,
            headless=bool(headless),
        )


__all__ = [
    "BrowserPoolConfig",
    "DEFAULT_HEADED_CONTEXTS_PER_BROWSER",
    "DEFAULT_HEADLESS_CONTEXTS_PER_BROWSER",
]
