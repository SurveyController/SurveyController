from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, Signal
from surveycore.core.questions.config import QuestionEntry
from surveycore.providers.contracts import SurveyQuestionMeta, ensure_survey_question_metas

from software.core.config.schema import RuntimeConfig
from software.providers.common import detect_survey_provider
from software.ui.pages.workbench.question_editor.utils import (
    build_entry_info_list,
    migrate_question_ids,
)


class WorkbenchState(QObject):
    configChanged = Signal(object, object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._config = RuntimeConfig()
        self._entry_questions_info: list[SurveyQuestionMeta] = []

    @property
    def entries(self) -> list[QuestionEntry]:
        return self.get_entries()

    @property
    def questions_info(self) -> list[SurveyQuestionMeta]:
        return deepcopy(self._config.questions_info or [])

    @property
    def entry_questions_info(self) -> list[SurveyQuestionMeta]:
        return deepcopy(self._entry_questions_info)

    def snapshot(self) -> RuntimeConfig:
        return deepcopy(self._config)

    def apply_config(self, config: RuntimeConfig) -> None:
        self._config = deepcopy(config)
        self._prepare_entries()
        self.configChanged.emit(self.snapshot(), frozenset(self._config.__dataclass_fields__))

    def update_settings(self, **changes: Any) -> None:
        updated = replace(self._config, **deepcopy(changes))
        changed_fields = frozenset(
            field for field, value in changes.items() if getattr(self._config, field) != value
        )
        if not changed_fields:
            return
        self._config = updated
        if changed_fields & {"question_entries", "questions_info"}:
            self._prepare_entries()
        self.configChanged.emit(self.snapshot(), changed_fields)

    def set_url(self, url: str) -> None:
        text = url.strip()
        if text == self._config.url:
            return
        self.update_settings(url=text, survey_provider=detect_survey_provider(text, default=""))

    def set_questions(self, info: list[SurveyQuestionMeta], entries: list[QuestionEntry]) -> None:
        self.set_entries(entries, info)

    def set_entries(
        self, entries: list[QuestionEntry], info: list[SurveyQuestionMeta] | None = None
    ) -> None:
        self._config.question_entries = deepcopy(list(entries))
        if info is not None:
            self._config.questions_info = deepcopy(ensure_survey_question_metas(info))
        self._prepare_entries()
        self.configChanged.emit(
            self.snapshot(),
            frozenset({"question_entries", "questions_info"}),
        )

    def _prepare_entries(self) -> None:
        entries = self._config.question_entries
        questions = self._config.questions_info or []
        migrate_question_ids(entries, questions)
        self._entry_questions_info = build_entry_info_list(entries, questions)
        for entry, question in zip(entries, self._entry_questions_info, strict=False):
            if not entry.question_title:
                entry.question_title = str(question.title or "").strip()

    def get_entries(self) -> list[QuestionEntry]:
        return deepcopy(self._config.question_entries)

    def append_entry(self, entry: QuestionEntry) -> None:
        self.set_entries([*self.entries, entry])

    def has_question_entries(self) -> bool:
        return bool(self._config.question_entries)
