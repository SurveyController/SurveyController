from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AIBatchItem:
    item_id: str
    question_type: str
    question_content: str
    blank_count: Optional[int] = None


@dataclass(frozen=True)
class AIBatchResult:
    completed: dict[str, list[str]]
    failed: dict[str, str]


@dataclass(frozen=True)
class AIPrefillSummary:
    requested: int = 0
    completed: int = 0
    failed: int = 0
