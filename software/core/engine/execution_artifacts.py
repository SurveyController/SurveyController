from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from surveycore.core.reverse_fill import ReverseFillSpec
from surveycore.providers.contracts import SurveyQuestionMeta

from software.core.task import ExecutionConfig


@dataclass(frozen=True)
class PreparedExecutionArtifacts:
    execution_config_template: ExecutionConfig
    survey_provider: str
    question_entries: list[Any]
    questions_info: list[SurveyQuestionMeta]
    reverse_fill_spec: ReverseFillSpec | None


class RuntimePreparationError(Exception):
    def __init__(
        self, user_message: str, *, log_message: str = "", detailed: bool = False,
    ) -> None:
        super().__init__(str(user_message or "运行准备失败"))
        self.user_message = str(user_message or "运行准备失败")
        self.log_message = str(log_message or self.user_message)
        self.detailed = bool(detailed)
