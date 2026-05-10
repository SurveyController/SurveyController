"""运行时布局相关的纯工具函数。"""

from __future__ import annotations


def build_owner_window_positions(owner_count: int) -> list[tuple[int, int]]:
    positions: list[tuple[int, int]] = []
    for owner_index in range(max(1, int(owner_count or 1))):
        positions.append((50 + owner_index * 60, 50 + owner_index * 60))
    return positions


__all__ = ["build_owner_window_positions"]
