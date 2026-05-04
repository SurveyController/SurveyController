"""Status bus for async runtime to Qt boundary."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, Callable, DefaultDict, Optional


class AsyncStatusBus:
    """Ordered status sink with lightweight throttling support."""

    def __init__(
        self,
        *,
        dispatcher: Optional[Callable[[Callable[[], Any]], Any]] = None,
        throttle_seconds: float = 0.075,
    ) -> None:
        self._dispatcher = dispatcher
        self._throttle_seconds = max(0.0, float(throttle_seconds or 0.0))
        self._lock = threading.Lock()
        self._sequence_by_slot: DefaultDict[str, int] = defaultdict(int)
        self._last_emit_by_slot: dict[str, float] = {}

    def emit(self, event: dict[str, Any]) -> None:
        payload = dict(event or {})
        slot_id = str(payload.get("slot_id") or payload.get("slot_label") or "global")
        now = time.monotonic()
        with self._lock:
            self._sequence_by_slot[slot_id] += 1
            payload["sequence"] = self._sequence_by_slot[slot_id]
            event_type = str(payload.get("type") or "")
            high_frequency = event_type in {"progress", "status"}
            last_emit = self._last_emit_by_slot.get(slot_id, 0.0)
            if high_frequency and self._throttle_seconds > 0 and (now - last_emit) < self._throttle_seconds:
                return
            self._last_emit_by_slot[slot_id] = now

        dispatcher = self._dispatcher
        if not callable(dispatcher):
            return

        def _deliver() -> None:
            callback = payload.get("callback")
            if callable(callback):
                callback()

        dispatcher(_deliver)


__all__ = ["AsyncStatusBus"]
