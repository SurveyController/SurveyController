"""统一封装常用 InfoBar 行为。"""

from __future__ import annotations

from typing import Optional

from qfluentwidgets import InfoBar, InfoBarPosition


def show_message_bar(
    *,
    parent,
    message: str,
    level: str = "info",
    title: str = "",
    position=InfoBarPosition.TOP,
    duration: int = 2000,
) -> InfoBar:
    """按级别创建统一样式的消息条。"""
    kind = str(level or "info").strip().lower()
    factory = {
        "success": InfoBar.success,
        "warning": InfoBar.warning,
        "error": InfoBar.error,
        "info": InfoBar.info,
    }.get(kind, InfoBar.info)
    return factory(
        str(title or ""),
        str(message or ""),
        parent=parent,
        position=position,
        duration=duration,
    )


def replace_message_bar(current: Optional[InfoBar]) -> None:
    """关闭旧消息条，避免重复堆叠。"""
    if current is None:
        return
    current.close()
