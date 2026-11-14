from __future__ import annotations

from enum import StrEnum


class RunPhase(StrEnum):
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    FINISHED = "finished"
    FAILED = "failed"


class PauseReason(StrEnum):
    USER = "user"
    PROXY_UNAVAILABLE = "proxy_unavailable"
    VERIFICATION = "verification"
    QUOTA = "quota"


class ProgressKind(StrEnum):
    WAITING = "waiting"
    PREPARING = "preparing"
    SUBMITTING = "submitting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


__all__ = ["PauseReason", "ProgressKind", "RunPhase"]
