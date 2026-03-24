"""进程级清理工具。"""
from __future__ import annotations

import subprocess
import threading

_BROWSER_PROCESS_NAMES = ("chrome.exe", "msedge.exe", "chromium.exe")
_NO_WINDOW = 0x08000000


def kill_browser_processes() -> None:
    """异步清理浏览器进程。"""

    def _do_kill() -> None:
        for name in _BROWSER_PROCESS_NAMES:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    creationflags=_NO_WINDOW,
                )
            except Exception:
                continue

    threading.Thread(target=_do_kill, daemon=True, name="BrowserKiller").start()

