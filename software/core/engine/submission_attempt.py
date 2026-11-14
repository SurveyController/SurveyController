from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AttemptState(StrEnum):
    PREPARING = "preparing"
    SUBMITTING = "submitting"
    COMMITTED = "committed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


@dataclass
class SubmissionAttempt:
    state: AttemptState = AttemptState.PREPARING

    def begin_submission(self) -> None:
        if self.state is not AttemptState.PREPARING:
            raise RuntimeError(f"不能从 {self.state.value} 开始提交")
        self.state = AttemptState.SUBMITTING

    def resolve(self, state: AttemptState) -> None:
        if self.state is not AttemptState.SUBMITTING:
            raise RuntimeError(f"不能从 {self.state.value} 结束提交")
        if state not in {AttemptState.COMMITTED, AttemptState.REJECTED, AttemptState.UNKNOWN}:
            raise ValueError(f"无效的提交结果：{state.value}")
        self.state = state


__all__ = ["AttemptState", "SubmissionAttempt"]
