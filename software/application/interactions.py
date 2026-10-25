from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4
from concurrent.futures import Future
from threading import Lock
from typing import Callable


class InteractionKind(StrEnum):
    NOTICE = "notice"
    QUOTA = "quota"


@dataclass(frozen=True)
class InteractionRequest:
    kind: InteractionKind
    code: str
    detail: str = ""
    level: str = "info"
    request_id: str = ""

    @classmethod
    def create(
        cls,
        kind: InteractionKind,
        code: str,
        *,
        detail: str = "",
        level: str = "info",
    ) -> InteractionRequest:
        return cls(kind, code, detail, level, str(uuid4()))


class InteractionBroker:
    """Correlate requests and replies without blocking an engine or GUI thread."""

    def __init__(self, publish: Callable[[InteractionRequest], None]) -> None:
        self._publish = publish
        self._lock = Lock()
        self._pending: dict[str, Future[bool]] = {}
        self._closed = False

    def request(self, request: InteractionRequest) -> Future[bool]:
        future: Future[bool] = Future()
        with self._lock:
            if self._closed:
                future.set_result(False)
                return future
            self._pending[request.request_id] = future
        try:
            self._publish(request)
        except Exception:
            self.resolve(request.request_id, False)
        return future

    def resolve(self, request_id: str, accepted: bool) -> None:
        with self._lock:
            future = self._pending.pop(request_id, None)
        if future is not None and not future.done():
            future.set_result(bool(accepted))

    def cancel_pending(self) -> None:
        with self._lock:
            self._closed = True
            pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_result(False)
