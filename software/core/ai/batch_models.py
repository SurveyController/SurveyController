from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PendingAIAnswer:
    item_id: str
    expected_count: int = 1


@dataclass(frozen=True)
class ResolvedAIAnswer:
    item_id: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class AIBatchItem:
    item_id: str
    question_type: str
    question_content: str
    blank_count: Optional[int] = None


@dataclass(frozen=True)
class AIBatchResult:
    completed: dict[str, ResolvedAIAnswer]
    failed: dict[str, Exception]


@dataclass(frozen=True)
class AIPrefillSummary:
    requested: int = 0
    completed: int = 0
    failed: int = 0


__all__ = [
    "AIBatchItem",
    "AIBatchResult",
    "AIPrefillSummary",
    "PendingAIAnswer",
    "ResolvedAIAnswer",
]
