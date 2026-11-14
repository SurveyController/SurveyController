from __future__ import annotations

from enum import StrEnum
from typing import Any


class ReverseFillIntent(StrEnum):
    USE_SAMPLE = "use_sample"
    USE_CONFIGURED_ANSWER = "use_configured_answer"
    BLOCK = "block"


def resolve_reverse_fill_intent(plan: Any) -> ReverseFillIntent:
    status = str(getattr(plan, "status", "") or "").strip().lower()
    if status == "reverse_fill":
        return ReverseFillIntent.USE_SAMPLE
    if status == "fallback_config" and bool(getattr(plan, "fallback_ready", False)):
        return ReverseFillIntent.USE_CONFIGURED_ANSWER
    return ReverseFillIntent.BLOCK


__all__ = ["ReverseFillIntent", "resolve_reverse_fill_intent"]
