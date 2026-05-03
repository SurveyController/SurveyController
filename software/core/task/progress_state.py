"""ExecutionState 的线程进度相关状态与辅助方法。"""

from __future__ import annotations

import time
from dataclasses import dataclass
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Protocol


@dataclass
class ThreadProgressState:
    """单个工作线程的运行状态快照。"""

    thread_name: str
    thread_index: int = 0
    owner_id: int = 0
    success_count: int = 0
    fail_count: int = 0
    step_current: int = 0
    step_total: int = 0
    status_text: str = "等待中"
    running: bool = False
    last_update_ts: float = 0.0


if TYPE_CHECKING:
    class _ThreadProgressHost(Protocol):
        lock: threading.Lock
        thread_progress: dict[str, ThreadProgressState]

        @staticmethod
        def _resolve_thread_index(thread_name: str) -> int: ...

        @staticmethod
        def _format_thread_display_name(thread_name: str, thread_index: int) -> str: ...

        def _get_or_create_thread_state_locked(self, thread_name: str) -> ThreadProgressState: ...


class ThreadProgressMixin:
    @staticmethod
    def _resolve_thread_index(thread_name: str) -> int:
        text = str(thread_name or "").strip()
        if not text:
            return 0
        for prefix in ("Worker-", "Slot-"):
            if not text.startswith(prefix):
                continue
            suffix = text.split("-", 1)[1].strip()
            try:
                value = int(suffix)
                return value if value > 0 else 0
            except Exception:
                return 0
        tail = []
        for ch in reversed(text):
            if ch.isdigit():
                tail.append(ch)
            else:
                break
        if not tail:
            return 0
        try:
            return int("".join(reversed(tail)))
        except Exception:
            return 0

    @staticmethod
    def _format_thread_display_name(thread_name: str, thread_index: int) -> str:
        if thread_index > 0:
            text = str(thread_name or "").strip()
            if text.startswith("Slot-"):
                return f"会话 {thread_index}"
            return f"线程 {thread_index}"
        text = str(thread_name or "").strip()
        if text.startswith("Worker-?"):
            return "线程 ?"
        if text.startswith("Slot-?"):
            return "会话 ?"
        return text or "线程 ?"

    def _get_or_create_thread_state_locked(
        self: "_ThreadProgressHost",
        thread_name: str,
    ) -> ThreadProgressState:
        key = str(thread_name or "").strip() or "Worker-?"
        state = self.thread_progress.get(key)
        if state is not None:
            return state
        state = ThreadProgressState(
            thread_name=key,
            thread_index=self._resolve_thread_index(key),
            last_update_ts=time.time(),
        )
        self.thread_progress[key] = state
        return state

    def ensure_worker_threads(self: "_ThreadProgressHost", expected_count: int, *, prefix: str = "Worker") -> None:
        count = max(1, int(expected_count or 1))
        now = time.time()
        normalized_prefix = str(prefix or "Worker").strip() or "Worker"
        with self.lock:
            for idx in range(1, count + 1):
                name = f"{normalized_prefix}-{idx}"
                state = self.thread_progress.get(name)
                if state is None:
                    self.thread_progress[name] = ThreadProgressState(
                        thread_name=name,
                        thread_index=idx,
                        last_update_ts=now,
                    )
                else:
                    state.thread_index = idx
                    state.last_update_ts = now

    def update_thread_status(
        self: "_ThreadProgressHost",
        thread_name: str,
        status_text: str,
        *,
        running: bool | None = None,
    ) -> None:
        now = time.time()
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.status_text = str(status_text or "")
            if running is not None:
                state.running = bool(running)
            state.last_update_ts = now

    def update_thread_step(
        self: "_ThreadProgressHost",
        thread_name: str,
        step_current: int,
        step_total: int,
        *,
        status_text: str | None = None,
        running: bool | None = None,
    ) -> None:
        now = time.time()
        current = max(0, int(step_current or 0))
        total = max(0, int(step_total or 0))
        if total > 0:
            current = min(current, total)
        with self.lock:
            thread_state = self._get_or_create_thread_state_locked(thread_name)
            thread_state.step_current = current
            thread_state.step_total = total
            if status_text is not None:
                thread_state.status_text = str(status_text or "")
            if running is not None:
                thread_state.running = bool(running)
            thread_state.last_update_ts = now

    def increment_thread_success(
        self: "_ThreadProgressHost",
        thread_name: str,
        *,
        status_text: str = "提交成功",
    ) -> None:
        now = time.time()
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.success_count += 1
            if state.step_total > 0:
                state.step_current = state.step_total
            state.status_text = str(status_text or "提交成功")
            state.running = True
            state.last_update_ts = now

    def increment_thread_fail(
        self: "_ThreadProgressHost",
        thread_name: str,
        *,
        status_text: str = "失败重试",
    ) -> None:
        now = time.time()
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.fail_count += 1
            state.status_text = str(status_text or "失败重试")
            state.running = True
            state.last_update_ts = now

    def mark_thread_finished(
        self: "_ThreadProgressHost",
        thread_name: str,
        *,
        status_text: str = "已停止",
    ) -> None:
        now = time.time()
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.running = False
            state.status_text = str(status_text or "已停止")
            state.last_update_ts = now

    def snapshot_thread_progress(self: "_ThreadProgressHost") -> List[Dict[str, Any]]:
        with self.lock:
            rows = []
            for state in self.thread_progress.values():
                total = max(0, int(state.step_total or 0))
                current = max(0, int(state.step_current or 0))
                if total > 0:
                    current = min(current, total)
                    step_percent = int(min(100, (current / float(total)) * 100))
                else:
                    step_percent = 0
                rows.append(
                    {
                        "thread_name": state.thread_name,
                        "thread_display_name": self._format_thread_display_name(
                            state.thread_name,
                            int(state.thread_index or 0),
                        ),
                        "thread_index": int(state.thread_index or 0),
                        "success_count": int(state.success_count or 0),
                        "fail_count": int(state.fail_count or 0),
                        "step_current": current,
                        "step_total": total,
                        "step_percent": step_percent,
                        "status_text": str(state.status_text or ""),
                        "running": bool(state.running),
                        "last_update_ts": float(state.last_update_ts or 0.0),
                    }
                )
        rows.sort(
            key=lambda item: (
                item["thread_index"] <= 0,
                item["thread_index"] if item["thread_index"] > 0 else 10**9,
                item["thread_name"],
            )
        )
        return rows
