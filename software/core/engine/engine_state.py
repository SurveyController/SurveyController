from __future__ import annotations

from enum import Enum


class EngineState(Enum):
    OPEN = "open"
    RUNNING = "running"
    STOPPING = "stopping"
    CLOSED = "closed"


__all__ = ["EngineState"]
