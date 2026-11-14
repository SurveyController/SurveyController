from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha1
from typing import Any, Iterable, NewType

from surveycore.providers.contracts import SurveyQuestionMeta

from software.core.config.codec import (
    build_runtime_config_snapshot,
    deserialize_runtime_config,
    serialize_runtime_config,
)
from software.core.config.schema import RuntimeConfig

QuestionId = NewType("QuestionId", str)


def question_id(question: SurveyQuestionMeta | Any, *, index: int = 0) -> QuestionId:
    stored = str(getattr(question, "question_id", "") or "").strip()
    if stored:
        return QuestionId(stored)
    provider = (
        str(
            getattr(question, "provider", None)
            or getattr(question, "survey_provider", None)
            or "wjx"
        )
        .strip()
        .lower()
    )
    provider_id = str(getattr(question, "provider_question_id", "") or "").strip()
    page_id = str(getattr(question, "provider_page_id", "") or "").strip()
    if provider_id:
        return QuestionId(
            f"{provider}:{page_id}:{provider_id}" if page_id else f"{provider}:{provider_id}"
        )
    raw = "|".join(
        (
            provider,
            page_id,
            str(getattr(question, "num", 0) or getattr(question, "question_num", 0) or 0),
            str(getattr(question, "title", "") or "").strip(),
        )
    )
    digest = sha1(raw.encode("utf-8")).hexdigest()[:12]
    return QuestionId(f"{provider}:local:{digest}")


@dataclass(frozen=True)
class RunPlan:
    _serialized_config: str
    question_ids: tuple[QuestionId, ...]

    @property
    def config(self) -> RuntimeConfig:
        return deserialize_runtime_config(json.loads(self._serialized_config))

    @property
    def question_entries(self) -> tuple[Any, ...]:
        return tuple(self.config.question_entries or ())


def compile_run_plan(
    config: RuntimeConfig,
    *,
    question_entries: Iterable[Any] | None = None,
    questions_info: Iterable[SurveyQuestionMeta] | None = None,
) -> RunPlan:
    snapshot = build_runtime_config_snapshot(
        config,
        question_entries=list(question_entries) if question_entries is not None else None,
        questions_info=list(questions_info) if questions_info is not None else None,
    )
    info = list(snapshot.questions_info or [])
    entries = list(snapshot.question_entries or [])
    for index, entry in enumerate(entries):
        if not getattr(entry, "question_id", None):
            source = next(
                (
                    item
                    for item in info
                    if int(getattr(item, "num", 0) or 0)
                    == int(getattr(entry, "question_num", 0) or 0)
                ),
                info[index] if index < len(info) else entry,
            )
            setattr(entry, "question_id", str(question_id(source, index=index)))
    ids = tuple(question_id(entry, index=index) for index, entry in enumerate(entries))
    if len(ids) != len(set(ids)):
        raise ValueError("运行计划包含重复的题目 ID")
    serialized_config = json.dumps(
        serialize_runtime_config(snapshot, include_secrets=True),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return RunPlan(_serialized_config=serialized_config, question_ids=ids)


__all__ = ["QuestionId", "RunPlan", "compile_run_plan", "question_id"]
