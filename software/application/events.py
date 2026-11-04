from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class ApplicationEventType(StrEnum):
    RUN_FAILED = "run_failed"
    CLEANUP_FINISHED = "cleanup_finished"
    AI_UNSTABLE = "ai_unstable"
    SUBMISSION_VERIFICATION_REQUIRED = "submission_verification_required"


@dataclass(frozen=True)
class ApplicationEvent:
    type: ApplicationEventType
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": str(self.type), **dict(self.payload)}


def event_payload(
    event_type: ApplicationEventType | str,
    **payload: Any,
) -> ApplicationEvent:
    return ApplicationEvent(type=ApplicationEventType(event_type), payload=payload)


__all__ = ["ApplicationEvent", "ApplicationEventType", "event_payload"]
